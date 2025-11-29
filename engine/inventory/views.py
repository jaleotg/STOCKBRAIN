from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from .models import InventoryItem, Unit, ItemGroup


# Do wyboru ilości rekordów na stronę
PAGE_SIZE_CHOICES = [50, 100, 200, 500, "all"]


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
# HOME (TABLE + PAGINATION + DROPDOWNS)
# ============================================

@login_required
def home_view(request):
    """
    Main inventory view:
    - pagination
    - page size selection
    - dropdowns Units / Groups
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

    # --- QUERYSET ---
    queryset = InventoryItem.objects.all().order_by("rack", "shelf", "box", "name")

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

    units = Unit.objects.all().order_by("code")
    groups = ItemGroup.objects.all().order_by("name")

    context = {
        "items": items,
        "units": units,
        "groups": groups,

        "page_obj": page_obj,
        "is_paginated": is_paginated,
        "page_size": page_size,
        "page_size_choices": PAGE_SIZE_CHOICES,
        "current_page_number": current_page_number,
        "num_pages": num_pages,

        # new pagination helpers
        "page_numbers": page_numbers,
        "show_first_ellipsis": show_first_ellipsis,
        "show_last_ellipsis": show_last_ellipsis,
    }

    return render(request, "home.html", context)


# ============================================
# AJAX: UPDATE UNIT (FK)
# ============================================

@login_required
@require_POST
def update_unit(request):
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
# AJAX: INLINE FIELD EDITING (TEXT / NUMBER)
# ============================================

@login_required
@require_POST
def update_field(request):
    """
    Universal inline editing endpoint.
    Expects:
        item_id
        field
        value
    """
    item_id = request.POST.get("item_id")
    field = request.POST.get("field")
    value = request.POST.get("value")

    if not item_id or not field:
        return JsonResponse({"ok": False, "error": "Missing parameters"}, status=400)

    try:
        item = InventoryItem.objects.get(pk=item_id)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item not found"}, status=404)

    # Security: allow only real editable fields
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
    }

    if field not in allowed_fields:
        return JsonResponse({"ok": False, "error": "Field not editable"}, status=400)

    # Convert numbers if needed
    if field in ["quantity_in_stock", "reorder_level", "reorder_time_days", "quantity_in_reorder"]:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid number"}, status=400)

    if field == "price":
        try:
            value = float(value)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid price"}, status=400)

    setattr(item, field, value)
    item.save()

    return JsonResponse({"ok": True, "value": value})
