from django.contrib import admin

from .models import PoetryType, PoetryText


@admin.register(PoetryType)
class PoetryTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name", "description")
    ordering = ("name",)


@admin.register(PoetryText)
class PoetryTextAdmin(admin.ModelAdmin):
    list_display = ("poetry_type", "created_by", "short_text")
    list_select_related = ("poetry_type", "created_by")
    search_fields = ("text", "created_by__username", "created_by__email")
    list_filter = ("poetry_type",)
    readonly_fields = ("created_by",)
    exclude = ("created_by",)

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @staticmethod
    def short_text(obj):
        text = (obj.text or "").strip()
        return (text[:80] + "...") if len(text) > 80 else text

    short_text.short_description = "Text"
