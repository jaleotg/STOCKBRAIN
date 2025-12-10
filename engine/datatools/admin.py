from django.contrib import admin
from .models import DataJob


@admin.register(DataJob)
class DataJobAdmin(admin.ModelAdmin):
    list_display = ("name", "direction", "mode", "source_type", "enabled", "last_run_at", "last_status")
    list_filter = ("direction", "mode", "source_type", "enabled")
    search_fields = ("name", "source_location", "notes", "last_status")
    readonly_fields = ("created_at", "updated_at", "last_run_at", "last_status")
