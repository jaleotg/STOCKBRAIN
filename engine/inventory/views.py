from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Prefetch

from .models import (
    InventoryItem,
    Unit,
    ItemGroup,
    InventoryUserMeta,
    InventoryColumn,
    FAVORITE_COLOR_CHOICES,
    InventorySettings,
)


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

    # --- SORTING (R, S, Name, Group) ---
    sort_field = request.GET.get("sort", "rack")
    sort_dir = request.GET.get("dir", "asc")

    # allowed sort fields
    allowed_sorts = {"rack", "shelf", "name", "group"}
    if sort_field not in allowed_sorts:
        sort_field = "rack"

    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"

    # build order_by args
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
        if sort_dir == "desc":
            order_by_args.append("-name")
        else:
            order_by_args.append("name")
        order_by_args.extend(["rack", "shelf", "box"])

    elif sort_field == "group":
        # sort by related group name
        if sort_dir == "desc":
            order_by_args.append("-group__name")
        else:
            order_by_args.append("group__name")
        order_by_args.extend(["rack", "shelf", "box", "name"])

    # fallback, gdyby coś się rozwaliło
    if not order_by_args:
        order_by_args = ["rack", "shelf", "box", "name"]

    # --- QUERYSET with per-user meta prefetch + sorting ---
    queryset = (
        InventoryItem.objects.all()
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

    if page_size == "all":
        # No pagination
        items = list(queryset)
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
    if settings_obj:
        restricted_fields = set(
            settings_obj.restricted_columns.values_list("field_name", flat=True)
        )

    # Słownik definicji kolumn (pod tooltipy / pełne nazwy)
    columns = {col.field_name: col for col in InventoryColumn.objects.all()}

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

        # Pagination helpers
        "page_numbers": page_numbers,
        "show_first_ellipsis": show_first_ellipsis,
        "show_last_ellipsis": show_last_ellipsis,

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
