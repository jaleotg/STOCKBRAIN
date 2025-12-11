from django.contrib import admin
from .models import (
    VehicleLocation,
    StandardWorkHours,
    JobState,
    WorkLog,
    WorkLogEntry,
    WorklogEmailSettings,
)


@admin.register(VehicleLocation)
class VehicleLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "location_type", "short_number", "full_number", "description")
    list_filter = ("location_type",)
    search_fields = ("name", "short_number", "full_number", "description")


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


class WorkLogEntryInline(admin.TabularInline):
    model = WorkLogEntry
    extra = 0
    fields = ("vehicle_location", "state", "job_description", "part", "part_description", "unit", "quantity", "time_hours", "notes")


@admin.register(WorkLog)
class WorkLogAdmin(admin.ModelAdmin):
    list_display = ("wl_number", "due_date", "author", "start_time", "end_time", "created_at", "updated_at")
    search_fields = ("wl_number", "author__username", "author__first_name", "author__last_name")
    list_filter = ("due_date", "author")
    inlines = [WorkLogEntryInline]


@admin.register(WorkLogEntry)
class WorkLogEntryAdmin(admin.ModelAdmin):
    list_display = ("worklog", "vehicle_location", "state", "time_hours", "part")
    list_filter = ("state", "vehicle_location", "worklog")
    search_fields = ("job_description", "part_description", "notes", "worklog__wl_number")


@admin.register(WorklogEmailSettings)
class WorklogEmailSettingsAdmin(admin.ModelAdmin):
    list_display = ("recipient_email",)
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
