from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import DataJob, DatabaseToolsEntry


@admin.register(DataJob)
class DataJobAdmin(admin.ModelAdmin):
    list_display = ("name", "direction", "mode", "source_type", "enabled", "last_run_at", "last_status")
    list_filter = ("direction", "mode", "source_type", "enabled")
    search_fields = ("name", "source_location", "notes", "last_status")
    readonly_fields = ("created_at", "updated_at", "last_run_at", "last_status")


@admin.register(DatabaseToolsEntry)
class DatabaseToolsEntryAdmin(admin.ModelAdmin):
    change_list_template = "datatools/db_tools.html"

    def changelist_view(self, request, extra_context=None):
        return redirect(reverse("db_tools"))

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
