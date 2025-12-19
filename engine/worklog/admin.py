from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from types import MethodType
from .models import (
    VehicleLocation,
    StandardWorkHours,
    JobState,
    WorkLog,
    WorkLogEntry,
    WorklogEmailSettings,
    EditCondition,
)


@admin.register(VehicleLocation)
class VehicleLocationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "location_type",
        "short_number",
        "full_number",
        "description",
        "sort_index",
        "sort_controls",
    )
    list_filter = ("location_type",)
    search_fields = ("name", "short_number", "full_number", "description")
    ordering = ("sort_index", "name")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:pk>/move-up/",
                self.admin_site.admin_view(self.move_up),
                name="worklog_vehiclelocation_move_up",
            ),
            path(
                "<int:pk>/move-down/",
                self.admin_site.admin_view(self.move_down),
                name="worklog_vehiclelocation_move_down",
            ),
        ]
        return custom + urls

    def changelist_view(self, request, extra_context=None):
        self._ensure_contiguous_order()
        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        if not obj.sort_index:
            max_idx = VehicleLocation.objects.aggregate(max_idx=Max("sort_index"))["max_idx"] or 0
            obj.sort_index = max_idx + 1
        super().save_model(request, obj, form, change)

    def sort_controls(self, obj):
        up_url = reverse("admin:worklog_vehiclelocation_move_up", args=[obj.pk])
        down_url = reverse("admin:worklog_vehiclelocation_move_down", args=[obj.pk])
        return format_html(
            '<a class="button" href="{}" title="Move up">▲</a>&nbsp;'
            '<a class="button" href="{}" title="Move down">▼</a>',
            up_url,
            down_url,
        )

    sort_controls.short_description = "Order"

    def move_up(self, request, pk):
        return self._swap_position(request, pk, direction="up")

    def move_down(self, request, pk):
        return self._swap_position(request, pk, direction="down")

    def _swap_position(self, request, pk, direction):
        self._ensure_contiguous_order()
        obj = get_object_or_404(VehicleLocation, pk=pk)
        target_index = obj.sort_index - 1 if direction == "up" else obj.sort_index + 1
        if target_index < 1:
            messages.info(request, "Location is already at the top.")
            return redirect(self._changelist_url())
        try:
            neighbor = VehicleLocation.objects.get(sort_index=target_index)
        except VehicleLocation.DoesNotExist:
            messages.info(request, "Location is already at the bottom.")
            return redirect(self._changelist_url())

        with transaction.atomic():
            neighbor.sort_index, obj.sort_index = obj.sort_index, target_index
            neighbor.save(update_fields=["sort_index"])
            obj.save(update_fields=["sort_index"])

        return redirect(self._changelist_url())

    def _ensure_contiguous_order(self):
        ordered = VehicleLocation.objects.order_by("sort_index", "name", "pk")
        for idx, loc in enumerate(ordered, start=1):
            if loc.sort_index != idx:
                VehicleLocation.objects.filter(pk=loc.pk).update(sort_index=idx)

    def _changelist_url(self):
        return reverse("admin:worklog_vehiclelocation_changelist")


@admin.register(StandardWorkHours)
class StandardWorkHoursAdmin(admin.ModelAdmin):
    list_display = ("start_time", "end_time")

    def has_add_permission(self, request):
        if StandardWorkHours.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        # Do not allow deleting the singleton
        return False


@admin.register(JobState)
class JobStateAdmin(admin.ModelAdmin):
    list_display = ("short_name", "full_name")
    search_fields = ("short_name", "full_name", "description")


@admin.register(EditCondition)
class EditConditionAdmin(admin.ModelAdmin):
    list_display = ("only_last_wl_editable", "editable_time_since_created")
    fields = ("only_last_wl_editable", "editable_time_since_created")

    def has_add_permission(self, request):
        if EditCondition.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = EditCondition.objects.first()
        if not obj:
            obj = EditCondition.objects.create()
        return self.change_view(request, object_id=str(obj.pk), extra_context=extra_context)

class WorkLogEntryInline(admin.TabularInline):
    model = WorkLogEntry
    extra = 0
    fields = (
        "vehicle_location",
        "state",
        "job_description",
        "inventory_rack",
        "inventory_shelf",
        "inventory_box",
        "part_description",
        "unit",
        "quantity",
        "time_hours",
        "notes",
    )


@admin.register(WorkLog)
class WorkLogAdmin(admin.ModelAdmin):
    list_display = ("wl_number", "due_date", "author", "start_time", "end_time", "created_at", "updated_at")
    search_fields = ("wl_number", "author__username", "author__first_name", "author__last_name")
    list_filter = ("due_date", "author")
    inlines = [WorkLogEntryInline]


@admin.register(WorklogEmailSettings)
class WorklogEmailSettingsAdmin(admin.ModelAdmin):
    list_display = ("send_new", "recipient_email",)
    filter_horizontal = ("users",)

    def has_add_permission(self, request):
        # singleton – brak dodawania kolejnych wpisów
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # przekieruj bezpośrednio do jedynego obiektu (tworząc go, jeśli brak)
        obj = WorklogEmailSettings.objects.first()
        if not obj:
            obj = WorklogEmailSettings.objects.create(recipient_email="")
        return self.change_view(request, object_id=str(obj.pk), extra_context=extra_context)


# --- Custom admin menu ordering for worklog app ---
_original_get_app_list = admin.site.get_app_list
_MODEL_ORDER = [
    "Log List",
    "Log Edition Conditions",
    "Log Email Rules",
]


def _worklog_sorted_app_list(self, request, *args, **kwargs):
    app_list = _original_get_app_list(request, *args, **kwargs)
    for app in app_list:
        if app.get("app_label") == "worklog":
            app["models"].sort(
                key=lambda m: (
                    _MODEL_ORDER.index(m["name"])
                    if m["name"] in _MODEL_ORDER
                    else len(_MODEL_ORDER),
                    m["name"],
                )
            )
    return app_list


admin.site.get_app_list = MethodType(_worklog_sorted_app_list, admin.site)
