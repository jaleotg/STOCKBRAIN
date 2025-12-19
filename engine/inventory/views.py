import json
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction, IntegrityError
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
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from django.urls import reverse

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
from worklog.models import (
    WorkLog,
    WorkLogEntry,
    VehicleLocation,
    JobState,
    EditCondition,
    WorklogEmailSettings,
    StandardWorkHours,
    get_default_work_hours,
)
from worklog.docx_utils import render_worklog_docx
from worklog.models import WorkLogEntryStateChange
from worklog.email_utils import send_worklog_docx_email
from decimal import Decimal, InvalidOperation
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
# HELPERS: WORKLOG EMAIL SCHEDULING
# ============================================

KUWAIT_TZ = ZoneInfo("Asia/Kuwait")


def _get_email_rule(user, is_new):
    """
    Returns (recipient_email or None, rule or None) if sending is allowed
    for this user and operation (new/edit).
    """
    rule = WorklogEmailSettings.objects.first()
    if not rule:
        return None, None
    if is_new and not rule.send_new:
        return None, None
    if (not is_new) and (not rule.send_edit):
        return None, None
    if not rule.recipient_email:
        return None, None
    if rule.users.exists() and not rule.users.filter(pk=user.pk).exists():
        return None, None
    return rule.recipient_email, rule


def _compute_schedule_dt(due_date, end_time):
    """
    Build a Kuwait-aware datetime for the given due_date and end_time.
    If end_time is missing, use StandardWorkHours.end_time.
    If resulting datetime is in the past (<= now), return a time on the next day.
    """
    if not due_date:
        return None
    target_time = end_time
    if target_time is None:
        _, target_time = get_default_work_hours()
    if target_time is None:
        return None
    naive_dt = datetime.combine(due_date, target_time)
    sched_dt = naive_dt.replace(tzinfo=KUWAIT_TZ)
    now_kw = timezone.now().astimezone(KUWAIT_TZ)
    if sched_dt <= now_kw:
        sched_dt = sched_dt + timedelta(days=1)
    return sched_dt


def _format_quantity_str(value):
    if value is None:
        return ""
    if isinstance(value, Decimal):
        normalized = value.normalize()
        text = format(normalized, "f")
    else:
        text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _build_worklog_parts(entries):
    parts = []
    tokens = []
    seen = set()
    for entry in entries:
        if entry.inventory_rack is None:
            continue
        loc_display = entry.inventory_location_display
        if not loc_display:
            continue
        token = f"{entry.inventory_rack}|{(entry.inventory_shelf or '').upper()}|{entry.inventory_box or ''}"
        if token not in seen:
            seen.add(token)
            tokens.append(token)
        parts.append(
            {
                "location": loc_display,
                "description": (entry.part_description or "").strip() or "—",
                "quantity": _format_quantity_str(entry.quantity),
                "unit": entry.unit.code if entry.unit else "",
            }
        )
    return parts, tokens


def _mark_email_pending(wl, sched_dt):
    wl.email_pending = True
    wl.email_scheduled_at = sched_dt
    wl.email_sent_at = None
    wl.save(update_fields=["email_pending", "email_scheduled_at", "email_sent_at"])


def _mark_email_sent(wl):
    now_val = timezone.now()
    wl.email_pending = False
    wl.email_scheduled_at = None
    wl.email_sent_at = now_val
    wl.save(update_fields=["email_pending", "email_scheduled_at", "email_sent_at"])
    return now_val


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

def _get_inventory_location_options():
    rack_values = (
        InventoryItem.objects.order_by("rack")
        .values_list("rack", flat=True)
        .distinct()
    )
    shelf_values = (
        InventoryItem.objects.order_by("shelf")
        .values_list("shelf", flat=True)
        .distinct()
    )
    rack_options = [
        {"value": str(r), "label": str(r)}
        for r in rack_values
        if r is not None
    ]
    shelf_options = [
        {"value": str(s), "label": str(s).upper()}
        for s in shelf_values
        if s
    ]
    return rack_options, shelf_options


@login_required
def work_log_view(request):
    # defaults from StandardWorkHours + scheduling flag
    default_start = ""
    default_end = ""
    allow_schedule = False
    from worklog.models import StandardWorkHours  # lazy import to avoid circulars
    try:
        cfg = StandardWorkHours.objects.first()
        if cfg:
            default_start = cfg.start_time.isoformat(timespec="minutes")
            default_end = cfg.end_time.isoformat(timespec="minutes")
        rule = WorklogEmailSettings.objects.first()
        allow_schedule = bool(rule and rule.enable_scheduled_send)
    except Exception:
        pass

    # edit conditions
    cond = EditCondition.objects.first()
    only_last = cond.only_last_wl_editable if cond else False
    hours_limit = cond.editable_time_since_created if cond else 0
    # date filters
    now = timezone.now().date()
    filter_due = request.GET.get("due_range", "last_90")
    filter_loc = request.GET.get("loc", "").strip()
    filter_state = request.GET.get("state", "").strip()
    filter_future = request.GET.get("future", "show").strip() or "show"
    add_flag = request.GET.get("add", "").strip()
    allowed_keys = {"due_range", "loc", "state", "future", "add"}
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
                queryset=WorkLogEntry.objects.select_related("vehicle_location", "state", "unit"),
            )
        )
        .order_by("-created_at")
    )

    if date_start and date_end:
        range_q = Q(due_date__gte=date_start, due_date__lte=date_end)
        if filter_future == "show":
            range_q = range_q | Q(due_date__gt=now)
        worklogs_qs = worklogs_qs.filter(range_q)

    if filter_loc:
        worklogs_qs = worklogs_qs.filter(entries__vehicle_location_id=filter_loc)
    if filter_state:
        worklogs_qs = worklogs_qs.filter(entries__state_id=filter_state)
    if filter_future == "hide":
        worklogs_qs = worklogs_qs.filter(due_date__lte=now)

    now_dt = timezone.now()
    inventory_base_url = reverse("home")
    worklogs = []
    # Human-readable edit rules (global for this request)
    rule_parts = []
    if hours_limit > 0:
        rule_parts.append(f"Editable within {hours_limit} hours from creation.")
    else:
        rule_parts.append("No time limit.")
    if only_last:
        rule_parts.append("Only your latest work log can be edited.")
    rule_summary = " ".join(rule_parts)
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
        # Build tooltip describing current rules and status
        status_parts = []
        if hours_limit > 0:
            status_parts.append(
                f"Age {diff_hours:.1f}h; limit {hours_limit}h "
                f"({'ok' if time_ok else 'blocked'})"
            )
        if only_last:
            status_parts.append(
                "Latest required "
                f"({'ok' if last_ok else 'blocked'})"
            )
        if not status_parts:
            status_parts.append("Editable (no restrictions).")
        edit_hint = ("Edit allowed. " if can_edit else "Edit blocked. ") + " ".join(status_parts)
        edit_hint += " " + rule_summary
        parts_summary, location_tokens = _build_worklog_parts(wl.entries.all())
        parts_link = ""
        if location_tokens:
            query = urlencode({"wl_locations": ",".join(location_tokens)})
            parts_link = f"{inventory_base_url}?{query}"
        parts_summary_json = json.dumps(parts_summary, ensure_ascii=False)
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
                "edit_hint": edit_hint,
                "email_pending": wl.email_pending,
                "email_scheduled_at": wl.email_scheduled_at,
                "email_sent_at": wl.email_sent_at,
                "parts_summary": parts_summary,
                "parts_summary_json": parts_summary_json,
                "parts_link": parts_link,
            }
        )

    rack_options, shelf_options = _get_inventory_location_options()

    return render(
        request,
        "work_log.html",
        {
            "item_count": InventoryItem.objects.count(),
            "is_master": False,
            "hide_add": False,
            "worklogs": worklogs,
            "wl_vehicle_options": list(
                VehicleLocation.objects.values("id", "name").order_by("sort_index", "name")
            ),
            "wl_state_options": list(
                JobState.objects.values("id", "short_name", "full_name").order_by("short_name")
            ),
            "wl_unit_options": list(
                Unit.objects.values("id", "code").order_by("code")
            ),
            "wl_rack_options": rack_options,
            "wl_shelf_options": shelf_options,
            "wl_default_start": default_start,
            "wl_default_end": default_end,
            "wl_allow_schedule": allow_schedule,
            "due_range_options": due_range_options,
            "due_range_selected": filter_due,
            "filter_loc": filter_loc,
            "filter_state": filter_state,
            "filter_future": filter_future,
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
        JobState.objects.values(
            state_id=F("id"),
            state__short_name=F("short_name"),
        ).order_by("state__short_name")
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
    # If state is unchanged, do nothing (avoid logging noise)
    if old_state and old_state.id == new_state.id:
        history_lines = []
        for sc in (
            entry.state_changes.select_related("old_state", "new_state", "changed_by")
            .order_by("-changed_at")
        ):
            old_label = sc.old_state.short_name if sc.old_state else "—"
            new_label = sc.new_state.short_name if sc.new_state else "—"
            who = sc.changed_by.username if sc.changed_by else "unknown"
            when = sc.changed_at.strftime("%Y-%m-%d %H:%M")
            history_lines.append(f"{when}: {old_label} → {new_label} by {who}")
        history_str = "\n".join(history_lines) if history_lines else "No changes yet"
        return JsonResponse({"ok": True, "state": new_state.short_name, "history": history_str})

    entry.state = new_state
    entry.save(update_fields=["state"])

    WorkLogEntryStateChange.objects.create(
        entry=entry,
        old_state=old_state,
        new_state=new_state,
        changed_by=request.user,
    )
    history_lines = []
    for sc in (
        entry.state_changes.select_related("old_state", "new_state", "changed_by")
        .order_by("-changed_at")
    ):
        old_label = sc.old_state.short_name if sc.old_state else "—"
        new_label = sc.new_state.short_name if sc.new_state else "—"
        who = sc.changed_by.username if sc.changed_by else "unknown"
        when = sc.changed_at.strftime("%Y-%m-%d %H:%M")
        history_lines.append(f"{when}: {old_label} → {new_label} by {who}")
    history_str = "\n".join(history_lines) if history_lines else "No changes yet"

    return JsonResponse({"ok": True, "state": new_state.short_name, "history": history_str})


@login_required
def work_log_master_view(request):
    if not request.user.groups.filter(name__iexact="work_log_master").exists():
        return HttpResponseForbidden("Not allowed")

    # defaults from StandardWorkHours + scheduling flag
    default_start = ""
    default_end = ""
    allow_schedule = False
    from worklog.models import StandardWorkHours  # lazy import to avoid circulars
    try:
        cfg = StandardWorkHours.objects.first()
        if cfg:
            default_start = cfg.start_time.isoformat(timespec="minutes")
            default_end = cfg.end_time.isoformat(timespec="minutes")
        rule = WorklogEmailSettings.objects.first()
        allow_schedule = bool(rule and rule.enable_scheduled_send)
    except Exception:
        pass

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
                queryset=WorkLogEntry.objects.select_related("vehicle_location", "state", "unit"),
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
    inventory_base_url = reverse("home")
    for wl in worklogs_qs:
        locations = sorted({entry.vehicle_location.name for entry in wl.entries.all()})
        states = sorted({entry.state.short_name for entry in wl.entries.all() if entry.state})
        parts_summary, location_tokens = _build_worklog_parts(wl.entries.all())
        parts_link = ""
        if location_tokens:
            query = urlencode({"wl_locations": ",".join(location_tokens)})
            parts_link = f"{inventory_base_url}?{query}"
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
                "email_pending": wl.email_pending,
                "email_scheduled_at": wl.email_scheduled_at,
                "email_sent_at": wl.email_sent_at,
                "parts_summary": parts_summary,
                "parts_summary_json": json.dumps(parts_summary, ensure_ascii=False),
                "parts_link": parts_link,
            }
        )

    user_options = list(
        WorkLog.objects.values("author_id", "author__username")
        .order_by("author__username")
        .distinct()
    )

    rack_options, shelf_options = _get_inventory_location_options()

    return render(
        request,
        "work_log.html",
        {
            "item_count": InventoryItem.objects.count(),
            "is_master": True,
            "hide_add": True,
            "worklogs": worklogs,
            "wl_vehicle_options": list(
                VehicleLocation.objects.values("id", "name").order_by("sort_index", "name")
            ),
            "wl_state_options": list(
                JobState.objects.values("id", "short_name", "full_name").order_by("short_name")
            ),
            "wl_unit_options": list(
                Unit.objects.values("id", "code").order_by("code")
            ),
            "wl_rack_options": rack_options,
            "wl_shelf_options": shelf_options,
            "wl_default_start": default_start,
            "wl_default_end": default_end,
            "wl_allow_schedule": allow_schedule,
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
                        "vehicle_location", "state", "unit"
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
                "part_description": entry.part_description,
                "inventory_rack": entry.inventory_rack,
                "inventory_shelf": entry.inventory_shelf or "",
                "inventory_box": entry.inventory_box or "",
                "inventory_location": entry.inventory_location_display,
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
    racks = request.POST.getlist("entry_rack[]")
    shelves = request.POST.getlist("entry_shelf[]")
    boxes = request.POST.getlist("entry_box[]")
    part_descs = request.POST.getlist("entry_part_desc[]")
    units = request.POST.getlist("entry_unit[]")
    qtys = request.POST.getlist("entry_qty[]")
    entry_notes = request.POST.getlist("entry_notes[]")

    n = len(vehicles)
    if not n:
        raise ValidationError("At least one entry is required.")
    if not (
        len(jobs)
        == len(states)
        == len(times)
        == len(racks)
        == len(shelves)
        == len(boxes)
        == len(part_descs)
        == len(units)
        == len(qtys)
        == len(entry_notes)
        == n
    ):
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

        rack_val = racks[idx].strip()
        rack_int = None
        if rack_val:
            try:
                rack_int = int(rack_val)
            except ValueError:
                raise ValidationError(f"Row {idx+1}: invalid rack value.")
        shelf_val = shelves[idx].strip().upper()[:4]
        box_val = boxes[idx].strip()[:50]

        entries.append(
            {
                "vehicle": vehicle_obj,
                "state": state_obj,
                "job": job_text,
                "time": time_hours,
                "rack": rack_int,
                "shelf": shelf_val,
                "box": box_val,
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
    send_mode = (request.POST.get("send_mode") or "email_now").strip()

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
                    inventory_rack=entry["rack"],
                    inventory_shelf=entry["shelf"],
                    inventory_box=entry["box"],
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
                "error": "A work log with this number already exists. Please pick a different due date or edit the existing one.",
            },
            status=400,
        )
    except Exception:
        return JsonResponse({"ok": False, "error": "Save failed. Please try again."}, status=500)

    # email handling
    email_recipient = None
    scheduled_at = None
    if send_mode == "schedule":
        recipient, _rule = _get_email_rule(request.user, is_new=True)
        if not recipient:
            return JsonResponse({"ok": True, "id": wl.id, "number": wl.wl_number})
        sched_dt = _compute_schedule_dt(wl.due_date, wl.end_time)
        if sched_dt is None:
            return JsonResponse({"ok": True, "id": wl.id, "number": wl.wl_number})
        now_kw = timezone.now().astimezone(KUWAIT_TZ)
        if sched_dt <= now_kw:
            try:
                email_recipient = send_worklog_docx_email(wl, is_new=True)
                if email_recipient:
                    _mark_email_sent(wl)
            except Exception:
                pass
        else:
            _mark_email_pending(wl, sched_dt)
            scheduled_at = sched_dt.isoformat()
    else:
        try:
            email_recipient = send_worklog_docx_email(wl, is_new=True)
            if email_recipient:
                _mark_email_sent(wl)
        except Exception:
            pass

    return JsonResponse(
        {
            "ok": True,
            "id": wl.id,
            "number": wl.wl_number,
            "email_recipient": email_recipient,
            "scheduled_at": scheduled_at,
        }
    )


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
    send_mode = (request.POST.get("send_mode") or "email_now").strip()

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
                    inventory_rack=entry["rack"],
                    inventory_shelf=entry["shelf"],
                    inventory_box=entry["box"],
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
                "error": "A work log with this number already exists. Please pick a different due date or edit the existing one.",
            },
            status=400,
        )
    except Exception:
        return JsonResponse({"ok": False, "error": "Update failed. Please try again."}, status=500)

    email_recipient = None
    scheduled_at = None
    if send_mode == "schedule":
        recipient, _rule = _get_email_rule(request.user, is_new=False)
        if recipient:
            sched_dt = _compute_schedule_dt(wl.due_date, wl.end_time)
            if sched_dt:
                now_kw = timezone.now().astimezone(KUWAIT_TZ)
                if sched_dt <= now_kw:
                    try:
                        email_recipient = send_worklog_docx_email(wl, is_new=False)
                        if email_recipient:
                            _mark_email_sent(wl)
                    except Exception:
                        pass
                else:
                    _mark_email_pending(wl, sched_dt)
                    scheduled_at = sched_dt.isoformat()
    else:
        try:
            email_recipient = send_worklog_docx_email(wl, is_new=False)
            if email_recipient:
                _mark_email_sent(wl)
        except Exception:
            pass

    return JsonResponse(
        {
            "ok": True,
            "id": wl.id,
            "number": wl.wl_number,
            "email_recipient": email_recipient,
            "scheduled_at": scheduled_at,
        }
    )


@login_required
@require_POST
def send_work_log_now(request, pk):
    """Send a pending/scheduled work log immediately."""
    try:
        wl = WorkLog.objects.get(pk=pk)
    except WorkLog.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Work log not found."}, status=404)

    if wl.author != request.user and not request.user.is_staff:
        return JsonResponse({"ok": False, "error": "Not allowed."}, status=403)

    recipient, _rule = _get_email_rule(request.user, is_new=False)
    if not recipient:
        return JsonResponse({"ok": False, "error": "E-mail rule not configured for this user."}, status=400)

    try:
        email_recipient = send_worklog_docx_email(wl, is_new=False)
        if email_recipient:
            _mark_email_sent(wl)
        else:
            return JsonResponse({"ok": False, "error": "Send failed (no recipient)."}, status=500)
    except Exception:
        return JsonResponse({"ok": False, "error": "Send failed. Please try again."}, status=500)

    return JsonResponse(
        {
            "ok": True,
            "number": wl.wl_number,
            "recipient": email_recipient,
        }
    )


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

    wl_locations_param = (request.GET.get("wl_locations") or "").strip()
    wl_location_filters = []
    wl_locations_display = []
    if wl_locations_param:
        for token in wl_locations_param.split(","):
            token = token.strip()
            if not token:
                continue
            parts = token.split("|")
            if not parts:
                continue
            rack_part = parts[0].strip() if len(parts) > 0 else ""
            try:
                rack_val = int(rack_part)
            except (TypeError, ValueError):
                continue
            shelf_val = (parts[1].strip().upper() if len(parts) > 1 else "")
            box_val = (parts[2].strip() if len(parts) > 2 else "")
            wl_location_filters.append((rack_val, shelf_val, box_val))
            display = f"{rack_val}-{shelf_val or '---'}-{box_val or '---'}"
            wl_locations_display.append(display)

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
    if wl_location_filters:
        location_q = Q()
        for rack_val, shelf_val, box_val in wl_location_filters:
            cond = Q(rack=rack_val)
            if shelf_val:
                cond &= Q(shelf__iexact=shelf_val)
            if box_val:
                cond &= Q(box__iexact=box_val)
            location_q |= cond
        if location_q:
            base_qs = base_qs.filter(location_q)
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
        "wl_location_filters_display": wl_locations_display,

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
# SHARED HELPERS FOR INVENTORY PAGINATION / SORT
# ============================================


def _base_order_annotations(user):
    user_meta_qs = InventoryUserMeta.objects.filter(user=user, item_id=OuterRef("pk"))
    fav_color_subq = user_meta_qs.values("favorite_color")[:1]
    note_present_expr = Exists(user_meta_qs.exclude(note__isnull=True).exclude(note=""))

    return {
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
    }


def _get_order_by_args(sort_field, sort_dir):
    annotate_kwargs = {}
    order_by_args = []

    if sort_field == "name":
        annotate_kwargs.update({
            "name_lower": Lower("name"),
            "first_char": Substr("name", 1, 1),
            "name_digit_flag": Case(
                When(first_char__in=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], then=0),
                default=1,
                output_field=IntegerField(),
            ),
        })
        if sort_dir == "desc":
            order_by_args.extend(["name_digit_flag", "-name_lower"])
        else:
            order_by_args.extend(["name_digit_flag", "name_lower"])
        order_by_args.extend(["rack", "shelf", "box"])
    elif sort_field == "shelf":
        order_by_args.append("-shelf" if sort_dir == "desc" else "shelf")
        order_by_args.extend(["rack", "box", "name"])
    elif sort_field == "group":
        order_by_args.append("-group__name" if sort_dir == "desc" else "group__name")
        order_by_args.extend(["rack", "shelf", "box", "name"])
    elif sort_field == "location":
        annotate_kwargs.update({
            "location_box_num": Cast(
                NullIf(
                    Func(F("box"), Value(r"^([0-9]+).*$"), Value(r"\1"), function="regexp_replace"),
                    Value(""),
                ),
                IntegerField(),
            ),
            "location_box_num_last": Cast(
                NullIf(
                    Func(F("box"), Value(r".*?([0-9]+)(?!.*[0-9]).*$"), Value(r"\1"), function="regexp_replace"),
                    Value(""),
                ),
                IntegerField(),
            ),
            "location_box_tail": Func(
                Func(F("box"), Value(r"^([0-9]+)"), Value(""), function="regexp_replace"),
                Value(r"([0-9]+)(?!.*[0-9]).*$"),
                Value(""),
                function="regexp_replace",
            ),
            "location_box_num_missing": Case(
                When(location_box_num__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            "location_box_num_last_missing": Case(
                When(location_box_num_last__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        })
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
    elif sort_field == "rack":
        order_by_args.append("-rack" if sort_dir == "desc" else "rack")
        order_by_args.extend(["shelf", "box", "name"])

    if not order_by_args:
        order_by_args = ["rack", "shelf", "box", "name"]

    return annotate_kwargs, order_by_args


def _build_filtered_inventory_queryset(user, params):
    base_qs = InventoryItem.objects.annotate(**_base_order_annotations(user))

    rack_filter = params.get("rack_filter")
    rack_filter_int = None
    if rack_filter not in (None, ""):
        try:
            rack_filter_int = int(rack_filter)
        except (TypeError, ValueError):
            rack_filter_int = None

    group_filter = params.get("group_filter")
    group_filter_int = None
    if group_filter not in (None, ""):
        try:
            group_filter_int = int(group_filter)
        except (TypeError, ValueError):
            group_filter_int = None

    condition_filter = params.get("condition_filter") or ""
    unit_filter_code = (params.get("unit_filter") or "").strip()
    instock_filter = params.get("instock_filter") or ""
    price_filter = params.get("price_filter") or ""
    disc_filter = params.get("disc_filter") or ""
    rev_filter = params.get("rev_filter") or ""
    fav_filter = params.get("fav_filter") or ""
    reorder_filter = params.get("reorder_filter") or ""
    search_query = (params.get("search") or "").strip()
    search_fields_param = params.get("search_fields", "")

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
    if search_fields_param and search_fields_param.lower() in {"__all__", "all"}:
        selected_search_fields = allowed_search_fields
    else:
        selected_search_fields = [
            f for f in (s.strip() for s in search_fields_param.split(","))
            if f in allowed_search_fields
        ]

    if rack_filter_int is not None:
        base_qs = base_qs.filter(rack=rack_filter_int)
    if group_filter_int is not None:
        base_qs = base_qs.filter(group_id=group_filter_int)
    if condition_filter:
        base_qs = base_qs.filter(condition_status=condition_filter)

    if unit_filter_code:
        code_up = unit_filter_code.upper()
        unit_exists = Unit.objects.filter(code__iexact=code_up).exists()
        if unit_exists:
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
        else:
            unit_filter_code = ""

    if instock_filter == "yes":
        base_qs = base_qs.filter(quantity_in_stock__gte=1)
    elif instock_filter == "no":
        base_qs = base_qs.filter(Q(quantity_in_stock__lt=1) | Q(quantity_in_stock__isnull=True))

    if price_filter == "yes":
        base_qs = base_qs.filter(Q(price__gt=0) & Q(price__isnull=False))
    elif price_filter == "no":
        base_qs = base_qs.filter(Q(price__isnull=True) | Q(price__lte=0))

    if disc_filter == "yes":
        base_qs = base_qs.filter(discontinued=True)
    elif disc_filter == "no":
        base_qs = base_qs.filter(discontinued=False)

    if rev_filter == "yes":
        base_qs = base_qs.filter(verify=True)
    elif rev_filter == "no":
        base_qs = base_qs.filter(verify=False)

    if fav_filter == "yes":
        base_qs = base_qs.filter(fav_present_int=1)
    elif fav_filter == "no":
        base_qs = base_qs.filter(fav_present_int=0)

    if reorder_filter == "yes":
        base_qs = base_qs.filter(for_reorder_ann=1)
    elif reorder_filter == "no":
        base_qs = base_qs.filter(for_reorder_ann=0)

    if search_query:
        fields_to_search = selected_search_fields or allowed_search_fields
        search_q = Q()
        for field in fields_to_search:
            search_q |= Q(**{f"{field}__icontains": search_query})
        if fields_to_search:
            base_qs = base_qs.filter(search_q)

    return base_qs


def _compute_page_for_item(user, queryset, item_id, sort_field, sort_dir, page_size_raw):
    try:
        if page_size_raw == "all":
            page_size_int = None
        else:
            page_size_int = int(page_size_raw) if page_size_raw else 50
    except (TypeError, ValueError):
        page_size_int = 50

    base_annotations = _base_order_annotations(user)
    extra_annotations, order_by_args = _get_order_by_args(sort_field, sort_dir)
    base_annotations.update(extra_annotations)

    ordered_ids = list(
        queryset.annotate(**base_annotations)
        .order_by(*order_by_args)
        .values_list("id", flat=True)
    )
    try:
        idx = ordered_ids.index(item_id)
        row_number = idx + 1
    except ValueError:
        row_number = None

    page_for_item = 1
    if row_number is not None:
        if page_size_int:
            page_for_item = (row_number - 1) // page_size_int + 1
        else:
            page_for_item = 1
    return page_for_item


@login_required
@require_POST
def move_location(request):
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)

    item_id = request.POST.get("item_id")
    rack_raw = request.POST.get("rack")
    shelf_raw = (request.POST.get("shelf") or "").strip().upper()
    box = (request.POST.get("box") or "").strip()

    if not item_id:
        return JsonResponse({"ok": False, "error": "Missing item_id"}, status=400)
    try:
        rack = int(rack_raw)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid rack value"}, status=400)
    if rack < 1 or rack > 20:
        return JsonResponse({"ok": False, "error": "Rack must be between 1 and 20."}, status=400)
    if not shelf_raw or len(shelf_raw) != 1 or not shelf_raw.isalpha():
        return JsonResponse({"ok": False, "error": "Invalid shelf value"}, status=400)
    if not box:
        return JsonResponse({"ok": False, "error": "Box is required"}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)

    old_location = f"{item.rack}-{item.shelf}-{item.box}"

    item.rack = rack
    item.shelf = shelf_raw
    item.box = box
    item.save()

    params = request.POST
    sort_field = params.get("sort") or "rack"
    sort_dir = params.get("dir") or "asc"
    page_size_param = params.get("page_size")

    queryset = _build_filtered_inventory_queryset(request.user, params)
    page_for_item = _compute_page_for_item(
        request.user, queryset, item.id, sort_field, sort_dir, page_size_param
    )

    new_location = f"{item.rack}-{item.shelf}-{item.box}"
    return JsonResponse({
        "ok": True,
        "page": page_for_item,
        "name": item.name,
        "old_location": old_location,
        "new_location": new_location,
        "rack": item.rack,
        "shelf": item.shelf,
        "box": item.box,
    })


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
    page_size_val = data.get("page_size")

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

    page_for_item = _compute_page_for_item(
        request.user,
        InventoryItem.objects.all(),
        item.id,
        sort_field,
        sort_dir,
        page_size_val,
    )

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
