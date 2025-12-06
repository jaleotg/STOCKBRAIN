from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
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
)
from django.db.models.functions import Lower, Substr, RowNumber, Cast

from .models import (
    InventoryItem,
    Unit,
    ItemGroup,
    InventoryUserMeta,
    InventoryColumn,
    FAVORITE_COLOR_CHOICES,
    InventorySettings,
)


def user_can_edit_or_json_error(request):
    if not user_can_edit(request.user):
        return JsonResponse({"ok": False, "error": "Permission denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)
    return None


# Do wyboru ilości rekordów na stronę
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
                    page_size = 50
            except ValueError:
                page_size = 50
    else:
        stored = request.session.get(session_key, 50)
        if stored == "all":
            page_size = "all"
        else:
            try:
                page_size = int(stored)
            except (TypeError, ValueError):
                page_size = 50

    # --- RACK FILTER ---
    rack_filter = request.GET.get("rack_filter")
    rack_filter_int = None
    if rack_filter:
        try:
            rack_filter_int = int(rack_filter)
        except ValueError:
            rack_filter_int = None

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
    if rack_filter_int is not None:
        base_qs = base_qs.filter(rack=rack_filter_int)
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
        # SQLite-friendly: use CAST(box AS INTEGER) to pull leading digits;
        # strings without digits cast to 0. This mimics numeric-first ordering.
        base_qs = base_qs.annotate(
            location_box_num=Cast("box", IntegerField())
        )
        if sort_dir == "desc":
            order_by_args.extend(["-rack", "-shelf", "-location_box_num", "-box", "name"])
        else:
            order_by_args.extend(["rack", "shelf", "location_box_num", "box", "name"])
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
    settings_obj = InventorySettings.objects.first()
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
