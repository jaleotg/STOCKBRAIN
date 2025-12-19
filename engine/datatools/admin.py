from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import (
    DatabaseExportEntry,
    DatabaseRestoreEntry,
    DatabaseDeleteEntry,
)


class _BaseDbToolsAdmin(admin.ModelAdmin):
    change_list_template = "datatools/db_tools.html"
    redirect_section = "export"

    def changelist_view(self, request, extra_context=None):
        url = f"{reverse('db_tools')}?section={self.redirect_section}"
        return redirect(url)

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


@admin.register(DatabaseExportEntry)
class DatabaseExportEntryAdmin(_BaseDbToolsAdmin):
    redirect_section = "export"


@admin.register(DatabaseRestoreEntry)
class DatabaseRestoreEntryAdmin(_BaseDbToolsAdmin):
    redirect_section = "restore"


@admin.register(DatabaseDeleteEntry)
class DatabaseDeleteEntryAdmin(_BaseDbToolsAdmin):
    redirect_section = "delete"
