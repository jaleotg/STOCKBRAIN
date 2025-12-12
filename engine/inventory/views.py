from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.db.models import (
    Prefetch,
    Case,
    When,
    IntegerField,
    Window,
    Value,
    Exists,
    OuterRef,
    Subquery,
    F,
    Q,
)
from django.db.models.functions import Lower, Substr, RowNumber, Cast, NullIf
from django.db.models import Func
from django.utils import timezone
from django.http import HttpResponseForbidden, Http404
from django.http import HttpResponse

from .models import (
    InventoryItem,
    Unit,
    ItemGroup,
    InventoryUserMeta,
    InventoryColumn,
    FAVORITE_COLOR_CHOICES,
    InventorySettings,
    get_user_profile,
)
from worklog.models import WorkLog, WorkLogEntry, VehicleLocation, JobState, EditCondition
from worklog.docx_utils import render_worklog_docx, generate_and_store_docx
from worklog.models import WorkLogEntryStateChange
from worklog.email_utils import send_worklog_docx_email
from decimal import Decimal, InvalidOperation
from datetime import datetime
from calendar import month_name, monthrange
from urllib.parse import urlencode


def user_can_edit_or_json_error(request):
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Permission denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)
    return None


# Do wyboru ilości rekordów na stronę (domyślnie 100)
PAGE_SIZE_CHOICES = [50, 100, 200, 500, "all"]


# ============================================
# HELPERS: ROLES
# ============================================

def user_is_editor(user):
    return user.groups.filter(name__iexact="editor").exists()


def user_is_purchase_admin(user):
    return user.groups.filter(name__iexact="purchase_manager").exists()


def user_can_edit(user):
    """
    Global "can edit inventory" flag:
    - editor
    - purchase_manager
    """
    return user_is_editor(user) or user_is_purchase_admin(user)


# ============================================
# LOGIN
# ============================================

def login_view(request):
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("home")
        else:
            error = "Invalid username or password."

    return render(request, "login.html", {"error": error})


# ============================================
# LOGOUT
# ============================================

@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def user_profile(request):
    profile = get_user_profile(request.user)

    if request.method == "GET":
        data = {
            "ok": True,
            "user": {
                "username": request.user.username,
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "email": request.user.email,
                "preferred_name": profile.preferred_name if profile else "",
            },
        }
        return JsonResponse(data)

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        preferred = (request.POST.get("preferred_name") or "").strip()
        old_pw = (request.POST.get("old_password") or "").strip()
        new_pw = (request.POST.get("new_password") or "").strip()
        new_pw_confirm = (request.POST.get("new_password_confirm") or "").strip()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                return JsonResponse({"ok": False, "error": "Invalid e-mail address."}, status=400)
        request.user.email = email
        request.user.save(update_fields=["email"])
        if profile:
            profile.preferred_name = preferred
            profile.save(update_fields=["preferred_name"])
        if new_pw:
            if not old_pw:
                return JsonResponse({"ok": False, "error": "Current password is required to change password."}, status=400)
            if not request.user.check_password(old_pw):
                return JsonResponse({"ok": False, "error": "Current password is incorrect."}, status=400)
            if new_pw != new_pw_confirm:
                return JsonResponse({"ok": False, "error": "New passwords do not match."}, status=400)
            if len(new_pw) < 6:
                return JsonResponse({"ok": False, "error": "New password must be at least 6 characters."}, status=400)
            request.user.set_password(new_pw)
            request.user.save(update_fields=["password"])
            update_session_auth_hash(request, request.user)
        return JsonResponse({"ok": True})

    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)


# ============================================
# WORK LOG (simple placeholder)
# ============================================

@login_required
def work_log_view(request):
    # defaults from StandardWorkHours
    default_start = ""
    default_end = ""
    from worklog.models import StandardWorkHours  # lazy import to avoid circulars
    cfg = StandardWorkHours.objects.first()
    if cfg:
        default_start = cfg.start_time.isoformat(timespec="minutes")
        default_end = cfg.end_time.isoformat(timespec="minutes")

    # edit conditions
    cond = EditCondition.objects.first()
    only_last = cond.only_last_wl_editable if cond else False
    hours_limit = cond.editable_time_since_created if cond else 0
    # date filters
    now = timezone.now().date()
    filter_due = request.GET.get("due_range", "last_90")
    filter_loc = request.GET.get("loc", "").strip()
    filter_state = request.GET.get("state", "").strip()
    allowed_keys = {"due_range", "loc", "state"}
    extra_keys = set(request.GET.keys()) - allowed_keys
    if extra_keys:
        clean_params = {}
        for k in allowed_keys:
            val = request.GET.get(k, "").strip()
            if val:
                clean_params[k] = val
        query = urlencode(clean_params)
        target = request.path
        if query:
            target = f"{target}?{query}"
        return redirect(target)

    def month_bounds(year, month):
        start = datetime(year, month, 1).date()
        end = datetime(year, month, monthrange(year, month)[1]).date()
        return start, end

    date_start = date_end = None
    if filter_due == "last_90":
        date_end = now
        date_start = now - timezone.timedelta(days=90)
    elif filter_due in ("curr_week", "prev_week"):
        # week starts on Sunday
        shift = (now.weekday() + 1) % 7  # Monday=0 ... Sunday=6 -> 0
        date_start = now - timezone.timedelta(days=shift)
        if filter_due == "prev_week":
            date_start = date_start - timezone.timedelta(days=7)
        date_end = date_start + timezone.timedelta(days=6)
    elif filter_due == "curr_month":
        date_start, date_end = month_bounds(now.year, now.month)
    elif filter_due == "prev_month":
        m = now.month - 1 or 12
        y = now.year if now.month > 1 else now.year - 1
        date_start, date_end = month_bounds(y, m)
    elif filter_due == "curr_year":
        date_start = datetime(now.year, 1, 1).date()
        date_end = datetime(now.year, 12, 31).date()
    elif filter_due == "prev_year":
        date_start = datetime(now.year - 1, 1, 1).date()
        date_end = datetime(now.year - 1, 12, 31).date()
    elif filter_due.startswith("month_"):
        try:
            offset = int(filter_due.split("_", 1)[1])
            ref = datetime(now.year, now.month, 15).date()
            # move back offset months
            month_idx = (ref.month - offset - 1) % 12 + 1
            year_idx = ref.year + ((ref.month - offset - 1) // 12)
            date_start, date_end = month_bounds(year_idx, month_idx)
        except Exception:
            date_start = date_end = None

    due_range_options = [
        {"value": "last_90", "label": "Last 90 days"},
        {"value": "curr_week", "label": "Current week"},
        {"value": "prev_week", "label": "Previous week"},
        {"value": "curr_month", "label": "Current month"},
        {"value": "prev_month", "label": "Previous month"},
        {"value": "curr_year", "label": "Current year"},
        {"value": "prev_year", "label": "Previous year"},
    ]
    for i in range(12):
        month_idx = (now.month - i - 1) % 12 + 1
        year_idx = now.year + ((now.month - i - 1) // 12)
        due_range_options.append(
            {
                "value": f"month_{i}",
                "label": f"{month_name[month_idx]} {year_idx}",
            }
        )

    last_wl_id = (
        WorkLog.objects.filter(author=request.user)
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first()
    )

    worklogs_qs = (
        WorkLog.objects.filter(author=request.user)
        .prefetch_related(
            Prefetch(
                "entries",
                queryset=WorkLogEntry.objects.select_related("vehicle_location", "state"),
            )
        )
        .order_by("-created_at")
    )

    if date_start and date_end:
        worklogs_qs = worklogs_qs.filter(due_date__gte=date_start, due_date__lte=date_end)

    if filter_loc:
        worklogs_qs = worklogs_qs.filter(entries__vehicle_location_id=filter_loc)
    if filter_state:
        worklogs_qs = worklogs_qs.filter(entries__state_id=filter_state)

    now_dt = timezone.now()
    worklogs = []
    for wl in worklogs_qs:
        locations = sorted(
            {entry.vehicle_location.name for entry in wl.entries.all()}
        )
        states = sorted(
            {entry.state.short_name for entry in wl.entries.all() if entry.state}
        )
        diff_hours = (now_dt - wl.created_at).total_seconds() / 3600.0
        time_ok = (hours_limit == 0) or (diff_hours <= hours_limit)
        last_ok = (not only_last) or (wl.id == last_wl_id)
        can_edit = time_ok and last_ok
        worklogs.append(
            {
                "id": wl.id,
                "number": wl.wl_number,
                "locations": ", ".join(locations) if locations else "—",
                "states": ", ".join(states) if states else "—",
                "note": wl.notes if wl.notes else "—",
                "created": wl.created_at,
                "updated": wl.updated_at,
                "can_edit": can_edit,
            }
        )

    return render(
        request,
        "work_log.html",
        {
            "item_count": InventoryItem.objects.count(),
            "is_master": False,
            "hide_add": False,
            "worklogs": worklogs,
            "wl_vehicle_options": list(
                VehicleLocation.objects.values("id", "name").order_by("name")
            ),
            "wl_state_options": list(
                JobState.objects.values("id", "short_name", "full_name").order_by("short_name")
            ),
            "wl_unit_options": list(
                Unit.objects.values("id", "code").order_by("code")
            ),
            "wl_default_start": default_start,
            "wl_default_end": default_end,
            "due_range_options": due_range_options,
            "due_range_selected": filter_due,
            "filter_loc": filter_loc,
            "filter_state": filter_state,
            "wl_user_options": [],
            "filter_user": "",
        },
    )


@login_required
def work_log_locations_view(request):
    # Filters
    filter_loc = request.GET.get("loc", "").strip()
    filter_user = request.GET.get("user", "").strip()
    filter_state = request.GET.get("state", "").strip()
    sort = request.GET.get("sort", "due")
    direction = request.GET.get("dir", "desc")

    order_map = {
        "due": "worklog__due_date",
        "created": "worklog__created_at",
    }
    order_field = order_map.get(sort, "worklog__due_date")
    if direction == "desc":
        order_field = f"-{order_field}"

    entries_qs = (
        WorkLogEntry.objects.select_related(
            "vehicle_location",
            "state",
            "worklog",
            "worklog__author",
        )
        .prefetch_related(
            Prefetch(
                "state_changes",
                queryset=WorkLogEntryStateChange.objects.select_related(
                    "old_state", "new_state", "changed_by"
                ).order_by("-changed_at"),
            )
        )
        .order_by(order_field)
    )

    if filter_loc:
        entries_qs = entries_qs.filter(vehicle_location_id=filter_loc)
    if filter_user:
        entries_qs = entries_qs.filter(worklog__author_id=filter_user)
    if filter_state:
        entries_qs = entries_qs.filter(state_id=filter_state)

    entries = []
    for en in entries_qs:
        history_lines = []
        for sc in en.state_changes.all():
            old_label = sc.old_state.short_name if sc.old_state else "—"
            new_label = sc.new_state.short_name if sc.new_state else "—"
            who = sc.changed_by.username if sc.changed_by else "unknown"
            when = sc.changed_at.strftime("%Y-%m-%d %H:%M")
            history_lines.append(f"{when}: {old_label} → {new_label} by {who}")
        history_str = "\n".join(history_lines) if history_lines else "No changes yet"
        entries.append(
            {
                "id": en.id,
                "state_id": en.state.id if en.state else "",
                "vehicle": en.vehicle_location.name if en.vehicle_location else "—",
                "job": en.job_description or "—",
                "state": en.state.short_name if en.state else "—",
                "note": en.notes or "—",
                "due": en.worklog.due_date,
                "created": en.worklog.created_at,
                "wl_number": en.worklog.wl_number,
                "author": en.worklog.author.username,
                "history": history_str,
            }
        )

    loc_options = list(
        WorkLogEntry.objects.filter(vehicle_location__isnull=False)
        .values("vehicle_location_id", "vehicle_location__name")
        .order_by("vehicle_location__name")
        .distinct()
    )
    user_options = list(
        WorkLog.objects.all()
        .values("author_id", "author__username")
        .order_by("author__username")
        .distinct()
    )
    state_options = list(
        WorkLogEntry.objects.filter(state__isnull=False)
        .values("state_id", "state__short_name")
        .order_by("state__short_name")
        .distinct()
    )

    return render(
        request,
        "work_log_locations.html",
        {
            "item_count": InventoryItem.objects.count(),
            "entries": entries,
            "filter_loc": filter_loc,
            "filter_user": filter_user,
            "filter_state": filter_state,
            "loc_options": loc_options,
            "user_options": user_options,
            "state_options": state_options,
            "sort": sort,
            "dir": direction,
        },
    )


@login_required
@require_POST
def change_worklog_entry_state(request, pk):
    """Change state of a worklog entry; allowed for any authenticated user (history is recorded)."""
    try:
        entry = WorkLogEntry.objects.select_related("worklog").get(pk=pk)
    except WorkLogEntry.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Entry not found."}, status=404)

    new_state_id = request.POST.get("state", "").strip()
    if not new_state_id:
        return JsonResponse({"ok": False, "error": "State is required."}, status=400)
    try:
        new_state = JobState.objects.get(pk=new_state_id)
    except JobState.DoesNotExist:
        return JsonResponse({"ok": False, "error": "State not found."}, status=400)

    old_state = entry.state
    entry.state = new_state
    entry.save(update_fields=["state"])

    WorkLogEntryStateChange.objects.create(
        entry=entry,
        old_state=old_state,
        new_state=new_state,
        changed_by=request.user,
    )
    return JsonResponse({"ok": True, "state": new_state.short_name})


@login_required
def work_log_master_view(request):
    if not request.user.groups.filter(name__iexact="work_log_master").exists():
        return HttpResponseForbidden("Not allowed")

    # defaults from StandardWorkHours
    default_start = ""
    default_end = ""
    from worklog.models import StandardWorkHours  # lazy import to avoid circulars
    cfg = StandardWorkHours.objects.first()
    if cfg:
        default_start = cfg.start_time.isoformat(timespec="minutes")
        default_end = cfg.end_time.isoformat(timespec="minutes")

    now = timezone.now().date()
    filter_due = request.GET.get("due_range", "last_90")
    filter_loc = request.GET.get("loc", "").strip()
    filter_state = request.GET.get("state", "").strip()
    filter_user = request.GET.get("user", "").strip()
    allowed_keys = {"due_range", "loc", "state", "user"}
    extra_keys = set(request.GET.keys()) - allowed_keys
    if extra_keys:
        clean_params = {}
        for k in allowed_keys:
            val = request.GET.get(k, "").strip()
            if val:
                clean_params[k] = val
        query = urlencode(clean_params)
        target = request.path
        if query:
            target = f"{target}?{query}"
        return redirect(target)

    def month_bounds(year, month):
        start = datetime(year, month, 1).date()
        end = datetime(year, month, monthrange(year, month)[1]).date()
        return start, end

    date_start = date_end = None
    if filter_due == "last_90":
        date_end = now
        date_start = now - timezone.timedelta(days=90)
    elif filter_due in ("curr_week", "prev_week"):
        shift = (now.weekday() + 1) % 7
        date_start = now - timezone.timedelta(days=shift)
        if filter_due == "prev_week":
            date_start = date_start - timezone.timedelta(days=7)
        date_end = date_start + timezone.timedelta(days=6)
    elif filter_due == "curr_month":
        date_start, date_end = month_bounds(now.year, now.month)
    elif filter_due == "prev_month":
        m = now.month - 1 or 12
        y = now.year if now.month > 1 else now.year - 1
        date_start, date_end = month_bounds(y, m)
    elif filter_due == "curr_year":
        date_start = datetime(now.year, 1, 1).date()
        date_end = datetime(now.year, 12, 31).date()
    elif filter_due == "prev_year":
        date_start = datetime(now.year - 1, 1, 1).date()
        date_end = datetime(now.year - 1, 12, 31).date()
    elif filter_due.startswith("month_"):
        try:
            offset = int(filter_due.split("_", 1)[1])
            ref = datetime(now.year, now.month, 15).date()
            month_idx = (ref.month - offset - 1) % 12 + 1
            year_idx = ref.year + ((ref.month - offset - 1) // 12)
            date_start, date_end = month_bounds(year_idx, month_idx)
        except Exception:
            date_start = date_end = None

    due_range_options = [
        {"value": "last_90", "label": "Last 90 days"},
        {"value": "curr_week", "label": "Current week"},
        {"value": "prev_week", "label": "Previous week"},
        {"value": "curr_month", "label": "Current month"},
        {"value": "prev_month", "label": "Previous month"},
        {"value": "curr_year", "label": "Current year"},
        {"value": "prev_year", "label": "Previous year"},
    ]
    for i in range(12):
        month_idx = (now.month - i - 1) % 12 + 1
        year_idx = now.year + ((now.month - i - 1) // 12)
        due_range_options.append(
            {
                "value": f"month_{i}",
                "label": f"{month_name[month_idx]} {year_idx}",
            }
        )

    worklogs_qs = (
        WorkLog.objects.all()
        .prefetch_related(
            Prefetch(
                "entries",
                queryset=WorkLogEntry.objects.select_related("vehicle_location", "state"),
            ),
            "author",
        )
        .order_by("-created_at")
    )

    if date_start and date_end:
        worklogs_qs = worklogs_qs.filter(due_date__gte=date_start, due_date__lte=date_end)
    if filter_loc:
        worklogs_qs = worklogs_qs.filter(entries__vehicle_location_id=filter_loc)
    if filter_state:
        worklogs_qs = worklogs_qs.filter(entries__state_id=filter_state)
    if filter_user:
        worklogs_qs = worklogs_qs.filter(author_id=filter_user)

    worklogs = []
    for wl in worklogs_qs:
        locations = sorted({entry.vehicle_location.name for entry in wl.entries.all()})
        states = sorted({entry.state.short_name for entry in wl.entries.all() if entry.state})
        worklogs.append(
            {
                "id": wl.id,
                "number": wl.wl_number,
                "locations": ", ".join(locations) if locations else "—",
                "states": ", ".join(states) if states else "—",
                "note": wl.notes if wl.notes else "—",
                "created": wl.created_at,
                "updated": wl.updated_at,
                "author": wl.author.username if wl.author else "—",
                "can_edit": False,
            }
        )

    user_options = list(
        WorkLog.objects.values("author_id", "author__username")
        .order_by("author__username")
        .distinct()
    )

    return render(
        request,
        "work_log.html",
        {
            "item_count": InventoryItem.objects.count(),
            "is_master": True,
            "hide_add": True,
            "worklogs": worklogs,
            "wl_vehicle_options": list(
                VehicleLocation.objects.values("id", "name").order_by("name")
            ),
            "wl_state_options": list(
                JobState.objects.values("id", "short_name", "full_name").order_by("short_name")
            ),
            "wl_unit_options": list(
                Unit.objects.values("id", "code").order_by("code")
            ),
            "wl_default_start": default_start,
            "wl_default_end": default_end,
            "due_range_options": due_range_options,
            "due_range_selected": filter_due,
            "filter_loc": filter_loc,
            "filter_state": filter_state,
            "wl_user_options": user_options,
            "filter_user": filter_user,
        },
    )




@login_required
def work_log_detail(request, pk):
    """Read-only detail of a single worklog for the current user."""
    try:
        wl = (
            WorkLog.objects.select_related("author")
            .prefetch_related(
                Prefetch(
                    "entries",
                    queryset=WorkLogEntry.objects.select_related(
                        "vehicle_location", "state", "part", "unit"
                    ),
                )
            )
            .get(pk=pk)
        )
    except WorkLog.DoesNotExist:
        raise Http404

    if wl.author != request.user and not request.user.is_staff:
        return HttpResponseForbidden("Not allowed")

    entries = []
    for entry in wl.entries.all():
        entries.append(
            {
                "vehicle": entry.vehicle_location.name,
                "vehicle_id": entry.vehicle_location.id,
                "state": entry.state.short_name,
                "state_id": entry.state.id,
                "job_description": entry.job_description,
                "part": entry.part.name if entry.part else "",
                "part_id": entry.part.id if entry.part else None,
                "part_description": entry.part_description,
                "quantity": entry.quantity,
                "unit": entry.unit.code if entry.unit else "",
                "unit_id": entry.unit.id if entry.unit else None,
                "time_hours": entry.time_hours,
                "notes": entry.notes,
            }
        )

    data = {
        "ok": True,
        "worklog": {
            "number": wl.wl_number,
            "id": wl.id,
            "due_date": wl.due_date.strftime("%Y-%m-%d") if wl.due_date else "",
            "created_at": wl.created_at,
            "updated_at": wl.updated_at,
            "start_time": wl.start_time.strftime("%H:%M") if wl.start_time else "",
            "end_time": wl.end_time.strftime("%H:%M") if wl.end_time else "",
            "notes": wl.notes,
            "author": wl.author.username,
            "user_full": f"{wl.author.first_name} {wl.author.last_name}".strip() or wl.author.username,
            "entries": entries,
        },
    }
    return JsonResponse(data)


@login_required
def download_work_log_docx(request, pk):
    """Generate and return the DOCX representation of a work log."""
    try:
        wl = WorkLog.objects.get(pk=pk)
    except WorkLog.DoesNotExist:
        raise Http404

    if wl.author != request.user and not request.user.is_staff:
        return HttpResponseForbidden("Not allowed")

    # Generate fresh DOCX bytes on demand (do not rely on stored file)
    content = render_worklog_docx(wl)
    filename = f"{wl.wl_number}.docx"
    resp = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError("Invalid due date format (YYYY-MM-DD).")


def _parse_time(val):
    val = (val or "").strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, "%H:%M").time()
    except ValueError:
        raise ValidationError("Invalid time format (HH:MM).")


def _prepare_entries_payload(request):
    vehicles = request.POST.getlist("entry_vehicle[]")
    jobs = request.POST.getlist("entry_job[]")
    states = request.POST.getlist("entry_state[]")
    times = request.POST.getlist("entry_time[]")
    parts = request.POST.getlist("entry_part[]")
    part_descs = request.POST.getlist("entry_part_desc[]")
    units = request.POST.getlist("entry_unit[]")
    qtys = request.POST.getlist("entry_qty[]")
    entry_notes = request.POST.getlist("entry_notes[]")

    n = len(vehicles)
    if not n:
        raise ValidationError("At least one entry is required.")
    if not (len(jobs) == len(states) == len(times) == len(parts) == len(part_descs) == len(units) == len(qtys) == len(entry_notes) == n):
        raise ValidationError("Entries payload is inconsistent.")

    entries = []
    for idx in range(n):
        veh_id = vehicles[idx].strip()
        state_id = states[idx].strip()
        job_text = jobs[idx].strip()
        time_val = times[idx].strip()
        if not (veh_id and state_id and job_text and time_val):
            raise ValidationError(f"Row {idx+1}: vehicle, state, job, and time are required.")
        try:
            vehicle_obj = VehicleLocation.objects.get(pk=int(veh_id))
        except (VehicleLocation.DoesNotExist, ValueError):
            raise ValidationError(f"Row {idx+1}: invalid vehicle/location.")
        try:
            state_obj = JobState.objects.get(pk=int(state_id))
        except (JobState.DoesNotExist, ValueError):
            raise ValidationError(f"Row {idx+1}: invalid state.")
        try:
            time_hours = Decimal(time_val)
        except (InvalidOperation, ValueError):
            raise ValidationError(f"Row {idx+1}: invalid time value.")

        part_obj = None
        part_val = parts[idx].strip()
        if part_val:
            try:
                part_obj = InventoryItem.objects.get(pk=int(part_val))
            except (InventoryItem.DoesNotExist, ValueError):
                part_obj = None

        unit_obj = None
        unit_val = units[idx].strip()
        if unit_val:
            try:
                unit_obj = Unit.objects.get(pk=int(unit_val))
            except (Unit.DoesNotExist, ValueError):
                unit_obj = None

        qty_dec = None
        qty_val = qtys[idx].strip()
        if qty_val:
            try:
                qty_dec = Decimal(qty_val)
            except (InvalidOperation, ValueError):
                raise ValidationError(f"Row {idx+1}: invalid quantity.")

        entries.append(
            {
                "vehicle": vehicle_obj,
                "state": state_obj,
                "job": job_text,
                "time": time_hours,
                "part": part_obj,
                "part_desc": part_descs[idx].strip(),
                "unit": unit_obj,
                "qty": qty_dec,
                "notes": entry_notes[idx].strip(),
            }
        )
    return entries


@login_required
@require_POST
def create_work_log(request):
    """Create a work log with entries from the add-work-log modal."""
    due_date_str = request.POST.get("due_date", "").strip()
    start_time_str = request.POST.get("start_time", "").strip()
    end_time_str = request.POST.get("end_time", "").strip()
    notes = request.POST.get("notes", "").strip()

    if not due_date_str:
        return JsonResponse({"ok": False, "error": "Due date is required."}, status=400)
    try:
        due_date = _parse_date(due_date_str)
    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)

    try:
        start_time = _parse_time(start_time_str)
        end_time = _parse_time(end_time_str)
    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)

    try:
        entries = _prepare_entries_payload(request)
    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)

    try:
        with transaction.atomic():
            wl = WorkLog.objects.create(
                due_date=due_date,
                author=request.user,
                start_time=start_time,
                end_time=end_time,
                notes=notes,
            )

            for entry in entries:
                WorkLogEntry.objects.create(
                    worklog=wl,
                    vehicle_location=entry["vehicle"],
                    job_description=entry["job"],
                    state=entry["state"],
                    part=entry["part"],
                    part_description=entry["part_desc"],
                    unit=entry["unit"],
                    quantity=entry["qty"],
                    time_hours=entry["time"],
                    notes=entry["notes"],
                )

    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)
    except IntegrityError:
        return JsonResponse(
            {
                "ok": False,
                "error": "A work log with this due date already exists. Please choose a different date.",
            },
            status=400,
        )
    except Exception:
        return JsonResponse({"ok": False, "error": "Save failed. Please try again."}, status=500)

    # DOCX is generated on demand (download/email); no need to persist here
    email_recipient = None
    try:
        email_recipient = send_worklog_docx_email(wl, is_new=True)
    except Exception:
        pass

    return JsonResponse({"ok": True, "id": wl.id, "number": wl.wl_number, "email_recipient": email_recipient})


@login_required
@require_POST
def update_work_log(request, pk):
    """Update an existing work log."""
    try:
        wl = WorkLog.objects.get(pk=pk)
    except WorkLog.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Work log not found."}, status=404)

    # permission: only author (apply conditions always)
    if wl.author != request.user:
        return JsonResponse({"ok": False, "error": "Not allowed."}, status=403)

    # edit conditions
    cond = EditCondition.objects.first()
    only_last = cond.only_last_wl_editable if cond else False
    hours_limit = cond.editable_time_since_created if cond else 0
    now = timezone.now()
    diff_hours = (now - wl.created_at).total_seconds() / 3600.0
    time_ok = (hours_limit == 0) or (diff_hours <= hours_limit)
    last_id = (
        WorkLog.objects.filter(author=request.user)
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first()
    )
    last_ok = (not only_last) or (wl.id == last_id)
    if not (time_ok and last_ok):
        return JsonResponse({"ok": False, "error": "Editing conditions are not met."}, status=403)

    due_date_str = request.POST.get("due_date", "").strip()
    start_time_str = request.POST.get("start_time", "").strip()
    end_time_str = request.POST.get("end_time", "").strip()
    notes = request.POST.get("notes", "").strip()

    if not due_date_str:
        return JsonResponse({"ok": False, "error": "Due date is required."}, status=400)
    try:
        due_date = _parse_date(due_date_str)
    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)

    try:
        start_time = _parse_time(start_time_str)
        end_time = _parse_time(end_time_str)
    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)

    try:
        entries = _prepare_entries_payload(request)
    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)

    try:
        with transaction.atomic():
            wl.due_date = due_date
            wl.start_time = start_time
            wl.end_time = end_time
            wl.notes = notes
            wl.save()
            wl.entries.all().delete()
            for entry in entries:
                WorkLogEntry.objects.create(
                    worklog=wl,
                    vehicle_location=entry["vehicle"],
                    job_description=entry["job"],
                    state=entry["state"],
                    part=entry["part"],
                    part_description=entry["part_desc"],
                    unit=entry["unit"],
                    quantity=entry["qty"],
                    time_hours=entry["time"],
                    notes=entry["notes"],
                )
    except ValidationError as ve:
        return JsonResponse({"ok": False, "error": str(ve)}, status=400)
    except IntegrityError:
        return JsonResponse(
            {
                "ok": False,
                "error": "A work log with this due date already exists. Please choose a different date.",
            },
            status=400,
        )
    except Exception:
        return JsonResponse({"ok": False, "error": "Update failed. Please try again."}, status=500)

    # DOCX is generated on demand (download/email); no need to persist here
    email_recipient = None
    try:
        email_recipient = send_worklog_docx_email(wl, is_new=False)
    except Exception:
        pass

    return JsonResponse({"ok": True, "id": wl.id, "number": wl.wl_number, "email_recipient": email_recipient})


@login_required
@require_POST
def delete_work_log(request, pk):
    """Delete a work log – only for the hardcoded super user leo-admin."""
    if request.user.username.lower() != "leo-admin":
        return JsonResponse({"ok": False, "error": "Not allowed."}, status=403)
    try:
        wl = WorkLog.objects.get(pk=pk)
    except WorkLog.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Work log not found."}, status=404)

    wl.delete()
    return JsonResponse({"ok": True})


# ============================================
# HOME (TABLE + PAGINATION + DROPDOWNS + USER META + SORTING)
# ============================================

@login_required
@ensure_csrf_cookie
def home_view(request):
    """
    Main inventory view:
    - pagination
    - page size selection
    - dropdowns Units / Groups / Condition
    - per-user meta: favorite_color + note (loaded via prefetch)
    - role awareness: editor / purchase_manager / read-only
    - server-side sorting by R / S / Name / Group
    """

    # --- PAGE SIZE (from GET or session) ---
    page_size_param = request.GET.get("page_size")
    session_key = "inventory_page_size"

    if page_size_param is not None:
        if page_size_param == "all":
            request.session[session_key] = "all"
            page_size = "all"
        else:
            try:
                page_size_int = int(page_size_param)
                if page_size_int in [50, 100, 200, 500]:
                    request.session[session_key] = page_size_int
                    page_size = page_size_int
                else:
                    page_size = 100
            except ValueError:
                page_size = 100
    else:
        stored = request.session.get(session_key, 100)
        if stored == "all":
            page_size = "all"
        else:
            try:
                page_size = int(stored)
            except (TypeError, ValueError):
                page_size = 100

    # --- RACK & GROUP FILTERS ---
    rack_filter = request.GET.get("rack_filter")
    rack_filter_int = None
    if rack_filter:
        try:
            rack_filter_int = int(rack_filter)
        except ValueError:
            rack_filter_int = None

    group_filter = request.GET.get("group_filter")
    group_filter_int = None
    if group_filter:
        try:
            group_filter_int = int(group_filter)
        except ValueError:
            group_filter_int = None

    # --- SEARCH (simple text, AND with filters) ---
    search_query = (request.GET.get("search") or "").strip()

    # zapamiętujemy wybór pól do wyszukiwania w sesji (per user)
    search_fields_session_key = "inventory_search_fields"
    if "search_fields" in request.GET:
        search_fields_param = request.GET.get("search_fields", "")
        request.session[search_fields_session_key] = search_fields_param
    else:
        search_fields_param = request.session.get(search_fields_session_key, "")
    allowed_search_fields = [
        "name",
        "part_description",
        "part_number",
        "dcm_number",
        "oem_name",
        "oem_number",
        "vendor",
        "source_location",
        "box",
        "group_name",
    ]
    if search_fields_param.lower() in ("all", "__all__"):
        selected_search_fields = allowed_search_fields
    else:
        selected_search_fields = [
            f for f in (s.strip() for s in search_fields_param.split(","))
            if f in allowed_search_fields
        ]

    # --- CONDITION FILTER ---
    condition_filter = request.GET.get("condition_filter") or ""

    # --- ADDITIONAL FILTERS ---
    unit_filter_code = (request.GET.get("unit_filter") or "").strip()
    instock_filter = request.GET.get("instock_filter") or ""
    price_filter = request.GET.get("price_filter") or ""
    disc_filter = request.GET.get("disc_filter") or ""
    rev_filter = request.GET.get("rev_filter") or ""
    fav_filter = request.GET.get("fav_filter") or ""
    reorder_filter = request.GET.get("reorder_filter") or ""

    # --- SORTING (R, S, Name, Group) ---
    sort_field = request.GET.get("sort", "rack")
    sort_dir = request.GET.get("dir", "asc")

    # allowed sort fields
    allowed_sorts = {
        "rack",
        "shelf",
        "name",
        "group",
        "location",
        "part_description",
        "part_number",
        "dcm_number",
        "oem_name",
        "oem_number",
        "vendor",
        "source_location",
        "unit",
        "quantity_in_stock",
        "price",
        "reorder_level",
        "reorder_time_days",
        "quantity_in_reorder",
        "condition_status",
        "discontinued",
        "verify",
        "favorite",
        "note",
        "for_reorder",
    }
    if sort_field not in allowed_sorts:
        sort_field = "rack"

    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"

    # Czy stosujemy specjalny klucz sortowania dla NAME?
    use_name_sort_key = (sort_field == "name")

    # Total items for header info
    item_count = InventoryItem.objects.count()

    # --- BASE QUERYSET + OPTIONAL ANNOTATIONS ---
    base_qs = InventoryItem.objects.all()

    # Per-user meta annotations (note/fav) + content presence flags
    user_meta_qs = InventoryUserMeta.objects.filter(user=request.user, item_id=OuterRef("pk"))
    fav_color_subq = user_meta_qs.values("favorite_color")[:1]
    note_present_expr = Exists(user_meta_qs.exclude(note__isnull=True).exclude(note=""))

    base_qs = base_qs.annotate(
        user_note_present=note_present_expr,
        user_fav_color=Subquery(fav_color_subq),
        desc_present=Case(
            When(part_description__isnull=True, then=Value(0)),
            When(part_description__exact="", then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        for_reorder_ann=Case(
            When(discontinued=True, then=Value(0)),
            When(reorder_level__isnull=True, then=Value(0)),
            When(quantity_in_stock__lte=F("reorder_level"), then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        note_present_int=Case(
            When(user_note_present=True, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        fav_present_int=Case(
            When(user_fav_color__isnull=True, then=Value(0)),
            When(user_fav_color__exact="", then=Value(0)),
            When(user_fav_color__iexact="NONE", then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    )
    filters_applied = False
    if rack_filter_int is not None:
        base_qs = base_qs.filter(rack=rack_filter_int)
        filters_applied = True
    if group_filter_int is not None:
        base_qs = base_qs.filter(group_id=group_filter_int)
        filters_applied = True
    if condition_filter:
        base_qs = base_qs.filter(condition_status=condition_filter)
        filters_applied = True
    if unit_filter_code:
        code_up = unit_filter_code.upper()
        unit_exists = Unit.objects.filter(code__iexact=code_up).exists()
        if unit_exists:
            # Dopuszczamy FK, kod oraz typowe warianty tekstowe z importu (np. ROLLS, METER)
            synonyms = {
                "ROLL": ["ROLL", "ROLLS"],
                "M": ["M", "METER", "METERS"],
                "CM": ["CM"],
                "MM": ["MM"],
                "LTR": ["LTR", "LITRE", "LITERS", "LITRES"],
                "ML": ["ML"],
                "PCS": ["PCS", "PC", "PIECES"],
                "PAIR": ["PAIR", "PAIRS"],
                "SET": ["SET", "SETS"],
                "KIT": ["KIT", "KITS"],
                "ORGANISER": ["ORGANISER", "ORGANIZER"],
                "BOX": ["BOX", "BOXES"],
                "CAN": ["CAN", "CANS"],
                "KGM": ["KGM", "KG", "KGS", "KILOGRAM", "KILOGRAMS"],
            }
            accepted_units = synonyms.get(code_up, [code_up])
            base_qs = base_qs.filter(
                Q(unit__code__iexact=code_up) |
                Q(units__in=accepted_units) |
                Q(units__iexact=code_up)
            )
            filters_applied = True
        else:
            # nieznany kod jednostki – ignorujemy filtr, by nie pokazywać pustych wyników
            unit_filter_code = ""
    if instock_filter == "yes":
        base_qs = base_qs.filter(quantity_in_stock__gte=1)
        filters_applied = True
    elif instock_filter == "no":
        base_qs = base_qs.filter(Q(quantity_in_stock__lt=1) | Q(quantity_in_stock__isnull=True))
        filters_applied = True
    if price_filter == "yes":
        base_qs = base_qs.filter(Q(price__gt=0) & Q(price__isnull=False))
        filters_applied = True
    elif price_filter == "no":
        base_qs = base_qs.filter(Q(price__isnull=True) | Q(price__lte=0))
        filters_applied = True
    if disc_filter == "yes":
        base_qs = base_qs.filter(discontinued=True)
        filters_applied = True
    elif disc_filter == "no":
        base_qs = base_qs.filter(discontinued=False)
        filters_applied = True
    if rev_filter == "yes":
        base_qs = base_qs.filter(verify=True)
        filters_applied = True
    elif rev_filter == "no":
        base_qs = base_qs.filter(verify=False)
        filters_applied = True
    if fav_filter == "yes":
        base_qs = base_qs.filter(fav_present_int=1)
        filters_applied = True
    elif fav_filter == "no":
        base_qs = base_qs.filter(fav_present_int=0)
        filters_applied = True
    if reorder_filter == "yes":
        base_qs = base_qs.filter(for_reorder_ann=1)
        filters_applied = True
    elif reorder_filter == "no":
        base_qs = base_qs.filter(for_reorder_ann=0)
        filters_applied = True
    if search_query:
        fields_to_search = selected_search_fields
        search_q = Q()
        for field in fields_to_search:
            search_q |= Q(**{f"{field}__icontains": search_query})
        if search_q and fields_to_search:
            base_qs = base_qs.filter(search_q)
            filters_applied = True
    if filters_applied:
        page_size = "all"

    if use_name_sort_key:
        # name_lower: sort case-insensitive
        # first_char: pierwszy znak
        # name_digit_flag: 0 gdy pierwsza cyfra, 1 gdy litera/inny znak
        base_qs = base_qs.annotate(
            name_lower=Lower("name"),
            first_char=Substr("name", 1, 1),
            name_digit_flag=Case(
                When(first_char__in=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], then=0),
                default=1,
                output_field=IntegerField(),
            ),
        )

    # --- SORT ORDER LIST ---
    order_by_args = []

    if sort_field == "rack":
        # primary: rack, then S/B/Name
        if sort_dir == "desc":
            order_by_args.append("-rack")
        else:
            order_by_args.append("rack")
        order_by_args.extend(["shelf", "box", "name"])

    elif sort_field == "shelf":
        if sort_dir == "desc":
            order_by_args.append("-shelf")
        else:
            order_by_args.append("shelf")
        order_by_args.extend(["rack", "box", "name"])

    elif sort_field == "name":
        # specjalne sortowanie:
        # - najpierw cyfry (name_digit_flag=0), potem litery (1)
        # - w ramach: rosnąco/malejąco po name_lower
        if sort_dir == "desc":
            order_by_args.append("name_digit_flag")
            order_by_args.append("-name_lower")
        else:
            order_by_args.append("name_digit_flag")
            order_by_args.append("name_lower")
        order_by_args.extend(["rack", "shelf", "box"])

    elif sort_field == "group":
        # sort by related group name
        if sort_dir == "desc":
            order_by_args.append("-group__name")
        else:
            order_by_args.append("group__name")
        order_by_args.extend(["rack", "shelf", "box", "name"])
    elif sort_field == "location":
        # Natural ordering: rack, shelf, numeric tokens inside box (all), then text tail.
        # Extract two numeric tokens: leading and last; use flags to push non-numeric last.
        base_qs = base_qs.annotate(
            location_box_num=Cast(
                NullIf(
                    Func(F("box"), Value(r"^([0-9]+).*$"), Value(r"\1"), function="regexp_replace"),
                    Value(""),
                ),
                IntegerField(),
            ),
            location_box_num_last=Cast(
                NullIf(
                    Func(F("box"), Value(r".*?([0-9]+)(?!.*[0-9]).*$"), Value(r"\1"), function="regexp_replace"),
                    Value(""),
                ),
                IntegerField(),
            ),
            location_box_tail=Func(
                Func(F("box"), Value(r"^([0-9]+)"), Value(""), function="regexp_replace"),
                Value(r"([0-9]+)(?!.*[0-9]).*$"),
                Value(""),
                function="regexp_replace",
            ),
            location_box_num_missing=Case(
                When(location_box_num__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            location_box_num_last_missing=Case(
                When(location_box_num_last__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
        if sort_dir == "desc":
            order_by_args.extend([
                "-rack",
                "-shelf",
                "location_box_num_missing",
                "-location_box_num",
                "location_box_num_last_missing",
                "-location_box_num_last",
                "-location_box_tail",
                "name",
            ])
        else:
            order_by_args.extend([
                "rack",
                "shelf",
                "location_box_num_missing",
                "location_box_num",
                "location_box_num_last_missing",
                "location_box_num_last",
                "location_box_tail",
                "name",
            ])
    elif sort_field == "part_description":
        # presence first (has content), then fallback by name
        if sort_dir == "desc":
            order_by_args.extend(["desc_present", "name"])
        else:
            order_by_args.extend(["-desc_present", "name"])
    elif sort_field == "part_number":
        order_by_args.append("-part_number" if sort_dir == "desc" else "part_number")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "dcm_number":
        order_by_args.append("-dcm_number" if sort_dir == "desc" else "dcm_number")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "oem_name":
        order_by_args.append("-oem_name" if sort_dir == "desc" else "oem_name")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "oem_number":
        order_by_args.append("-oem_number" if sort_dir == "desc" else "oem_number")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "vendor":
        order_by_args.append("-vendor" if sort_dir == "desc" else "vendor")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "source_location":
        order_by_args.append("-source_location" if sort_dir == "desc" else "source_location")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "unit":
        order_by_args.append("-unit__code" if sort_dir == "desc" else "unit__code")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "quantity_in_stock":
        order_by_args.append("-quantity_in_stock" if sort_dir == "desc" else "quantity_in_stock")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "price":
        order_by_args.append("-price" if sort_dir == "desc" else "price")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "reorder_level":
        order_by_args.append("-reorder_level" if sort_dir == "desc" else "reorder_level")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "reorder_time_days":
        order_by_args.append("-reorder_time_days" if sort_dir == "desc" else "reorder_time_days")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "quantity_in_reorder":
        order_by_args.append("-quantity_in_reorder" if sort_dir == "desc" else "quantity_in_reorder")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "condition_status":
        order_by_args.append("-condition_status" if sort_dir == "desc" else "condition_status")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "discontinued":
        order_by_args.append("-discontinued" if sort_dir == "desc" else "discontinued")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "verify":
        order_by_args.append("-verify" if sort_dir == "desc" else "verify")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "favorite":
        if sort_dir == "desc":
            order_by_args.extend(["fav_present_int", "user_fav_color", "rack", "shelf", "box"])
        else:
            order_by_args.extend(["-fav_present_int", "user_fav_color", "rack", "shelf", "box"])
    elif sort_field == "note":
        if sort_dir == "desc":
            order_by_args.extend(["note_present_int", "rack", "shelf", "box"])
        else:
            order_by_args.extend(["-note_present_int", "rack", "shelf", "box"])
    elif sort_field == "for_reorder":
        order_by_args.append("-for_reorder_ann" if sort_dir == "asc" else "for_reorder_ann")
        order_by_args.extend(["rack", "shelf", "box"])

    # fallback, gdyby coś się rozwaliło
    if not order_by_args:
        order_by_args = ["rack", "shelf", "box", "name"]

    # --- APPLY PREFETCH + ORDERING ---
    queryset = (
        base_qs
        .prefetch_related(
            Prefetch(
                "user_meta",
                queryset=InventoryUserMeta.objects.filter(user=request.user),
                to_attr="meta_for_user",
            )
        )
        .order_by(*order_by_args)
    )

    # --- PAGINATION ---
    page_obj = None
    is_paginated = False
    current_page_number = 1
    num_pages = 1
    page_numbers = []
    show_first_ellipsis = False
    show_last_ellipsis = False

    selected_rack_count = None
    if page_size == "all":
        # No pagination
        items = list(queryset)
        selected_rack_count = len(items)
    else:
        paginator = Paginator(queryset, page_size)
        page_number = request.GET.get("page", 1)
        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        items = page_obj.object_list
        is_paginated = paginator.num_pages > 1
        current_page_number = page_obj.number
        num_pages = paginator.num_pages

        # Smart window for numeric pagination
        if num_pages <= 7:
            # Show all page numbers
            page_numbers = list(range(1, num_pages + 1))
            show_first_ellipsis = False
            show_last_ellipsis = False
        else:
            # We always show:
            # - page 1
            # - some window around current_page_number (2..num_pages-1)
            # - page num_pages
            window_size = 5  # how many numbers in the middle
            start = max(current_page_number - 2, 2)
            end = min(current_page_number + 2, num_pages - 1)

            # Adjust window to always have "window_size" if possible
            if end - start + 1 < window_size:
                if start == 2:
                    end = min(start + window_size - 1, num_pages - 1)
                elif end == num_pages - 1:
                    start = max(end - window_size + 1, 2)

            page_numbers = list(range(start, end + 1))

            show_first_ellipsis = start > 2
            show_last_ellipsis = end < (num_pages - 1)

    # --- ROLES & COLUMN VISIBILITY ---
    user = request.user

    is_editor = user_is_editor(user)
    is_purchase_admin = user_is_purchase_admin(user)
    can_edit = is_editor or is_purchase_admin

    # Wczytanie ustawień i listy kolumn ograniczonych
    restricted_fields = set()
    settings_obj = InventorySettings.objects.order_by("-id").first()
    if settings_obj is None:
        # Ensure there is always a settings row, so admin choices take effect.
        settings_obj = InventorySettings.objects.create()
    restricted_fields = set(
        settings_obj.restricted_columns.values_list("field_name", flat=True)
    )

    # Słownik definicji kolumn (pod tooltipy / pełne nazwy)
    columns = {col.field_name: col for col in InventoryColumn.objects.all()}
    # Historycznie R/S/B były usunięte z InventoryColumn, ale szablon add‑item
    # wciąż odwołuje się do rack/shelf/box. Gdy brak wpisu w bazie – dodaj
    # tymczasowe „kolumny” żeby nie wywalać szablonu.
    from types import SimpleNamespace
    for _field, _label in [
        ("rack", "Rack"),
        ("shelf", "Shelf"),
        ("box", "Box"),
    ]:
        if _field not in columns:
            columns[_field] = SimpleNamespace(
                field_name=_field,
                full_label=_label,
                short_label="",
                functional_description="",
            )

    units = Unit.objects.all().order_by("code")
    groups = ItemGroup.objects.all().order_by("name")

    # Choices dla dropdownu CONDITION – bierzemy z definicji pola w modelu,
    # żeby zawsze było spójnie z bazą.
    try:
        condition_field = InventoryItem._meta.get_field("condition_status")
        condition_choices = list(condition_field.choices)
    except Exception:
        # Gdyby z jakiegoś powodu pole nie istniało (stara migracja itd.),
        # nie wysypujemy widoku.
        condition_choices = []

    rack_filter_values = list(
        InventoryItem.objects.values_list("rack", flat=True).distinct().order_by("rack")
    )

    context = {
        "items": items,
        "units": units,
        "groups": groups,
        "condition_choices": condition_choices,
        "favorite_color_choices": FAVORITE_COLOR_CHOICES,

        # Pagination
        "page_obj": page_obj,
        "is_paginated": is_paginated,
        "page_size": page_size,
        "page_size_choices": PAGE_SIZE_CHOICES,
        "current_page_number": current_page_number,
        "num_pages": num_pages,
        "rack_filter_values": rack_filter_values,

        # Pagination helpers
        "page_numbers": page_numbers,
        "show_first_ellipsis": show_first_ellipsis,
        "show_last_ellipsis": show_last_ellipsis,
        "rack_filter": rack_filter_int,
        "group_filter": group_filter_int,
        "condition_filter": condition_filter,
        "unit_filter": unit_filter_code,
        "instock_filter": instock_filter,
        "price_filter": price_filter,
        "disc_filter": disc_filter,
        "rev_filter": rev_filter,
        "fav_filter": fav_filter,
        "reorder_filter": reorder_filter,
        "selected_rack_count": selected_rack_count,
        "item_count": item_count,

        # Column settings from admin
        "columns": columns,                      # field_name → InventoryColumn
        "restricted_fields": restricted_fields,  # set pól tylko dla purchase_manager
        "is_purchase_admin": is_purchase_admin,  # bool: czy user w grupie purchase_manager

        # Roles for frontend
        "is_editor": is_editor,
        "can_edit": can_edit,

        # Sorting info for frontend (strzałki, aktywna kolumna)
        "sort_field": sort_field,
        "sort_dir": sort_dir,
        "rack_filter": rack_filter_int,
        "search_query": search_query,
        "search_fields": ",".join(selected_search_fields),
        "search_fields_list": selected_search_fields,
    }

    return render(request, "home.html", context)


# ============================================
# AJAX: UPDATE UNIT (FK)
# ============================================

@login_required
@require_POST
def update_unit(request):
    # only editor / purchase_manager
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)

    item_id = request.POST.get("item_id")
    unit_id = request.POST.get("unit_id")

    if not item_id or not unit_id:
        return JsonResponse({"ok": False, "error": "Missing parameters"}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
        unit = Unit.objects.get(pk=unit_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)
    except Unit.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Unit not found"}, status=404)

    # Synchronize FK + legacy text
    item.unit = unit
    item.units = unit.code
    item.save()

    return JsonResponse({"ok": True, "unit": unit.code})


# ============================================
# AJAX: UPDATE GROUP (FK)
# ============================================

@login_required
@require_POST
def update_group(request):
    # only editor / purchase_manager
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)

    item_id = request.POST.get("item_id")
    group_id = request.POST.get("group_id")

    if not item_id or not group_id:
        return JsonResponse({"ok": False, "error": "Missing parameters"}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
        group = ItemGroup.objects.get(pk=group_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)
    except ItemGroup.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Group not found"}, status=404)

    # Synchronize FK + legacy text
    item.group = group
    item.group_name = group.name
    item.save()

    return JsonResponse({"ok": True, "group": group.name})


# ============================================
# AJAX: INLINE FIELD EDITING (TEXT / NUMBER / BOOL / CHOICE)
# ============================================

@login_required
@require_POST
def update_field(request):
    """
    Universal inline editing endpoint for InventoryItem.
    Expects:
        item_id
        field
        value

    Only for:
        - editor
        - purchase_manager
    """
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)

    item_id = request.POST.get("item_id")
    field = request.POST.get("field")
    value = request.POST.get("value")

    if not item_id or not field:
        return JsonResponse({"ok": False, "error": "Missing parameters"}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)

    # Security: allow only real editable fields (front inline / dropdowny)
    allowed_fields = {
        "name",
        "part_description",
        "part_number",
        "dcm_number",
        "oem_name",
        "oem_number",
        "vendor",
        "source_location",
        "quantity_in_stock",
        "price",
        "reorder_level",
        "reorder_time_days",
        "quantity_in_reorder",
        "box",
        "rack",
        "shelf",
        "condition_status",   # CONDITION dropdown
        "verify",             # REV checkbox
        "discontinued",       # DISC checkbox
    }

    if field not in allowed_fields:
        return JsonResponse({"ok": False, "error": "Field not editable"}, status=400)

    # --- Typed conversion / validation ---

    # Integers
    if field in ["quantity_in_stock", "reorder_level", "reorder_time_days", "quantity_in_reorder"]:
        try:
            value_converted = int(value)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid number"}, status=400)

    # Price (decimal/float)
    elif field == "price":
        try:
            value_converted = float(value)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid price"}, status=400)

    # Booleans: verify / discontinued
    elif field in ["verify", "discontinued"]:
        text = (value or "").strip().lower()
        if text in ["1", "true", "t", "yes", "y", "on"]:
            value_converted = True
        elif text in ["0", "false", "f", "no", "n", "off", ""]:
            value_converted = False
        else:
            return JsonResponse({"ok": False, "error": "Invalid boolean"}, status=400)

    # CONDITION STATUS (choice)
    elif field == "condition_status":
        # validate against model choices so we don't zapisujemy śmieci
        try:
            cond_field = InventoryItem._meta.get_field("condition_status")
            valid_values = {choice_value for choice_value, _ in cond_field.choices}
        except Exception:
            valid_values = set()

        if valid_values and value not in valid_values and value != "":
            return JsonResponse({"ok": False, "error": "Invalid condition_status"}, status=400)

        # empty string -> None
        value_converted = value or None

    # All other text fields
    else:
        value_converted = value

    setattr(item, field, value_converted)
    item.save()

    return JsonResponse({"ok": True, "value": value_converted})


# ============================================
# AJAX: PER-USER FAVORITE COLOR (STAR)
# ============================================

@login_required
@require_POST
def update_favorite(request):
    """
    Update per-user favorite color for a given inventory item.
    Expects:
        item_id
        color  (one of FAVORITE_COLOR_CHOICES values, e.g. RED/GREEN/YELLOW/BLUE/NONE)

    Allowed for any authenticated user (including non-editor).
    """
    item_id = request.POST.get("item_id")
    color = (request.POST.get("color") or "NONE").upper()

    if not item_id:
        return JsonResponse({"ok": False, "error": "Missing item_id"}, status=400)

    valid_colors = {c for c, _ in FAVORITE_COLOR_CHOICES}
    if color not in valid_colors:
        return JsonResponse({"ok": False, "error": "Invalid color"}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)

    meta, created = InventoryUserMeta.objects.get_or_create(
        user=request.user,
        item=item,
        defaults={"favorite_color": color, "note": ""},
    )

    if not created:
        meta.favorite_color = color
        meta.save()

    return JsonResponse({"ok": True, "color": meta.favorite_color})


# ============================================
# AJAX: PER-USER NOTE
# ============================================

@login_required
@require_POST
def update_note(request):
    """
    Update per-user note (HTML) for a given inventory item.
    Expects:
        item_id
        note (HTML/string)

    Allowed for any authenticated user (including non-editor).
    """
    item_id = request.POST.get("item_id")
    note = request.POST.get("note") or ""

    if not item_id:
        return JsonResponse({"ok": False, "error": "Missing item_id"}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)

    meta, created = InventoryUserMeta.objects.get_or_create(
        user=request.user,
        item=item,
        defaults={"favorite_color": "NONE", "note": note},
    )

    if not created:
        meta.note = note
        meta.save()

    return JsonResponse({"ok": True})


# ============================================
# AJAX: CREATE ITEM
# ============================================

@login_required
@require_POST
def create_item(request):
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Permission denied"}, status=403)

    data = request.POST
    errors = []

    required_fields = ["rack", "shelf", "box", "unit_id", "quantity_in_stock"]

    def get_int(name, allow_none=False):
        val = data.get(name)
        if val in (None, ""):
            return None if allow_none else 0
        try:
            return int(val)
        except ValueError:
            errors.append(f"Invalid int for {name}")
            return None

    rack = get_int("rack")
    shelf = (data.get("shelf") or "").strip().upper()
    box = (data.get("box") or "").strip()

    group_id = data.get("group_id")
    name = (data.get("name") or "").strip()
    part_description = (data.get("part_description") or "").strip()
    part_number = (data.get("part_number") or "").strip()
    dcm_number = (data.get("dcm_number") or "").strip()
    oem_name = (data.get("oem_name") or "").strip()
    oem_number = (data.get("oem_number") or "").strip()
    vendor = (data.get("vendor") or "").strip()
    source_location = (data.get("source_location") or "").strip()

    unit_id = data.get("unit_id")
    quantity_in_stock = get_int("quantity_in_stock", allow_none=False)
    price = data.get("price")
    reorder_level = get_int("reorder_level", allow_none=True)
    reorder_time_days = get_int("reorder_time_days", allow_none=True)
    quantity_in_reorder = get_int("quantity_in_reorder", allow_none=True)
    condition_status = data.get("condition_status") or ""
    discontinued = data.get("discontinued") == "1"
    verify = data.get("verify") == "1"

    sort_field = data.get("sort") or "rack"
    sort_dir = data.get("dir") or "asc"
    try:
        page_size_val = data.get("page_size")
        if page_size_val == "all":
            page_size_int = None
        else:
            page_size_int = int(page_size_val) if page_size_val else 50
    except (TypeError, ValueError):
        page_size_int = 50

    for f in required_fields:
        if not data.get(f):
            errors.append(f"Missing required field: {f}")

    if errors:
        return JsonResponse({"ok": False, "error": "; ".join(errors)}, status=400)

    group_obj = None
    if group_id:
        try:
            group_obj = ItemGroup.objects.get(id=group_id)
        except ItemGroup.DoesNotExist:
            errors.append("Invalid group")

    unit_obj = None
    if unit_id:
        try:
            unit_obj = Unit.objects.get(id=unit_id)
        except Unit.DoesNotExist:
            errors.append("Invalid unit")

    if errors:
        return JsonResponse({"ok": False, "error": "; ".join(errors)}, status=400)

    try:
        item = InventoryItem.objects.create(
            rack=rack,
            shelf=shelf,
            box=box,
            group=group_obj,
            group_name=group_obj.name if group_obj else "",
            name=name,
            part_description=part_description,
            part_number=part_number,
            dcm_number=dcm_number,
            oem_name=oem_name,
            oem_number=oem_number,
            vendor=vendor,
            source_location=source_location,
            unit=unit_obj,
            units=unit_obj.code if unit_obj else "",
            quantity_in_stock=quantity_in_stock,
            price=price if price not in (None, "") else None,
            reorder_level=reorder_level,
            reorder_time_days=reorder_time_days,
            quantity_in_reorder=quantity_in_reorder,
            condition_status=condition_status or None,
            discontinued=discontinued,
            verify=verify,
        )
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)

    # --- compute page where item would appear with current sort + page size ---
    order_by_args = []
    annotate_kwargs = {}

    # per-user meta for note/fav
    user_meta_qs = InventoryUserMeta.objects.filter(user=request.user, item_id=OuterRef("pk"))
    fav_color_subq = user_meta_qs.values("favorite_color")[:1]
    note_present_expr = Exists(user_meta_qs.exclude(note__isnull=True).exclude(note=""))

    annotate_kwargs.update({
        "user_note_present": note_present_expr,
        "user_fav_color": Subquery(fav_color_subq),
        "desc_present": Case(
            When(part_description__isnull=True, then=Value(0)),
            When(part_description__exact="", then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        "for_reorder_ann": Case(
            When(discontinued=True, then=Value(0)),
            When(reorder_level__isnull=True, then=Value(0)),
            When(quantity_in_stock__lte=F("reorder_level"), then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        "note_present_int": Case(
            When(user_note_present=True, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        "fav_present_int": Case(
            When(user_fav_color__isnull=True, then=Value(0)),
            When(user_fav_color__exact="", then=Value(0)),
            When(user_fav_color__iexact="NONE", then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    })

    if sort_field == "rack":
        order_by_args.append("-rack" if sort_dir == "desc" else "rack")
        order_by_args.extend(["shelf", "box", "name"])
    elif sort_field == "shelf":
        order_by_args.append("-shelf" if sort_dir == "desc" else "shelf")
        order_by_args.extend(["rack", "box", "name"])
    elif sort_field == "name":
        annotate_kwargs["name_lower"] = Lower("name")
        annotate_kwargs["first_char"] = Substr("name", 1, 1)
        annotate_kwargs["name_digit_flag"] = Case(
            When(first_char__in=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], then=0),
            default=1,
            output_field=IntegerField(),
        )
        if sort_dir == "desc":
            order_by_args.extend(["name_digit_flag", "-name_lower"])
        else:
            order_by_args.extend(["name_digit_flag", "name_lower"])
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "group":
        order_by_args.append("-group__name" if sort_dir == "desc" else "group__name")
        order_by_args.extend(["rack", "shelf", "box", "name"])
    elif sort_field == "location":
        if sort_dir == "desc":
            order_by_args.extend(["-rack", "-shelf", "-box", "name"])
        else:
            order_by_args.extend(["rack", "shelf", "box", "name"])
    elif sort_field == "part_description":
        if sort_dir == "desc":
            order_by_args.extend(["desc_present", "name"])
        else:
            order_by_args.extend(["-desc_present", "name"])
    elif sort_field == "part_number":
        order_by_args.append("-part_number" if sort_dir == "desc" else "part_number")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "dcm_number":
        order_by_args.append("-dcm_number" if sort_dir == "desc" else "dcm_number")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "oem_name":
        order_by_args.append("-oem_name" if sort_dir == "desc" else "oem_name")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "oem_number":
        order_by_args.append("-oem_number" if sort_dir == "desc" else "oem_number")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "vendor":
        order_by_args.append("-vendor" if sort_dir == "desc" else "vendor")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "source_location":
        order_by_args.append("-source_location" if sort_dir == "desc" else "source_location")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "unit":
        order_by_args.append("-unit__code" if sort_dir == "desc" else "unit__code")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "quantity_in_stock":
        order_by_args.append("-quantity_in_stock" if sort_dir == "desc" else "quantity_in_stock")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "reorder_level":
        order_by_args.append("-reorder_level" if sort_dir == "desc" else "reorder_level")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "reorder_time_days":
        order_by_args.append("-reorder_time_days" if sort_dir == "desc" else "reorder_time_days")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "quantity_in_reorder":
        order_by_args.append("-quantity_in_reorder" if sort_dir == "desc" else "quantity_in_reorder")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "condition_status":
        order_by_args.append("-condition_status" if sort_dir == "desc" else "condition_status")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "discontinued":
        order_by_args.append("-discontinued" if sort_dir == "desc" else "discontinued")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "verify":
        order_by_args.append("-verify" if sort_dir == "desc" else "verify")
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "favorite":
        if sort_dir == "desc":
            order_by_args.extend(["fav_present_int", "user_fav_color", "rack", "shelf", "box"])
        else:
            order_by_args.extend(["-fav_present_int", "user_fav_color", "rack", "shelf", "box"])
    elif sort_field == "note":
        if sort_dir == "desc":
            order_by_args.extend(["note_present_int", "rack", "shelf", "box"])
        else:
            order_by_args.extend(["-note_present_int", "rack", "shelf", "box"])
    elif sort_field == "for_reorder":
        order_by_args.append("-for_reorder_ann" if sort_dir == "asc" else "for_reorder_ann")
        order_by_args.extend(["rack", "shelf", "box"])
    else:
        order_by_args = ["rack", "shelf", "box", "name"]

    # Oblicz pozycję nowego rekordu w aktualnym sortowaniu (prosto w Pythonie,
    # żeby uniknąć problemów z window functions)
    ordered_ids = list(
        InventoryItem.objects.annotate(**annotate_kwargs)
        .order_by(*order_by_args)
        .values_list("id", flat=True)
    )
    try:
        idx = ordered_ids.index(item.id)
        row_number = idx + 1  # 1-based
    except ValueError:
        row_number = None

    page_for_item = 1
    if row_number is not None:
        if page_size_int:
            page_for_item = (row_number - 1) // page_size_int + 1
        else:
            page_for_item = 1

    return JsonResponse({"ok": True, "id": item.id, "page": page_for_item})


# ============================================
# AJAX: DELETE ITEM (requires password)
# ============================================

@login_required
@require_POST
def delete_item(request):
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Permission denied"}, status=403)

    item_id = request.POST.get("item_id")
    password = request.POST.get("password") or ""

    if not item_id:
        return JsonResponse({"ok": False, "error": "Missing item_id"}, status=400)

    user = authenticate(request, username=request.user.username, password=password)
    if not user:
        return JsonResponse({"ok": False, "error": "Invalid password"}, status=403)

    try:
        item = InventoryItem.objects.get(pk=item_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)

    item.delete()
    return JsonResponse({"ok": True})
