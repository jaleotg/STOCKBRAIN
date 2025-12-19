from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import DatabaseToolsEntry


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
