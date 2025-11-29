from django.contrib import admin, messages
from django.shortcuts import redirect

from .models import (
    InventoryItem,
    InventoryColumn,
    InventorySettings,
    Unit,
    ItemGroup,
)
from .importers import import_inventory_from_excel


class InventoryImportExport(InventoryItem):
    """
    Proxy model used only to show a separate 'Import/Export' entry
    in the admin sidebar, under the Inventory app.
    """

    class Meta:
        proxy = True
        verbose_name = "Inventory import / export"
        verbose_name_plural = "Inventory import / export"


@admin.register(InventoryImportExport)
class InventoryImportExportAdmin(admin.ModelAdmin):
    """
    Custom admin that renders a simple page with an upload form
    (template: inventory_import_export.html) and calls the importer.
    """
    change_list_template = "inventory_import_export.html"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if request.method == "POST" and "excel_file" in request.FILES:
            uploaded_file = request.FILES["excel_file"]
            try:
                # Your importer can return (created, updated) or just a count.
                result = import_inventory_from_excel(uploaded_file)
                if isinstance(result, tuple) and len(result) == 2:
                    created, updated = result
                    messages.success(
                        request,
                        f"Import finished. Created: {created}, updated: {updated} items.",
                    )
                else:
                    messages.success(
                        request,
                        f"Import finished. Processed {result} items.",
                    )
            except Exception as exc:
                messages.error(request, f"Import failed: {exc}")
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(InventoryColumn)
class InventoryColumnAdmin(admin.ModelAdmin):
    """
    Editable dictionary of all logical columns used in the front-end table.

    - field_name: technical key linked to InventoryItem / UI
    - short_label: short label in the table header (R, S, B, RT, etc.)
    - full_label: full column name (for tooltips / lollipops)
    - functional_description: explanation of behaviour (editing, effects, etc.)
    """
    list_display = (
        "field_name",
        "short_label",
        "full_label",
        "functional_description_short",
    )
    list_editable = (
        "short_label",
        "full_label",
    )
    search_fields = (
        "field_name",
        "short_label",
        "full_label",
        "functional_description",
    )
    ordering = ("field_name",)
    list_per_page = 50

    # Disable bulk actions (including bulk delete)
    actions = None

    def has_add_permission(self, request):
        """
        Columns are created automatically by the application code.
        We do not allow manual creation from the admin UI.
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Deleting column definitions is dangerous, because the front-end
        and permissions logic rely on them. We disable delete in admin.
        """
        return False

    @staticmethod
    def functional_description_short(obj):
        """
        Shorten long descriptions so the list view stays readable.
        """
        text = (obj.functional_description or "").strip()
        if len(text) <= 80:
            return text
        return text[:77] + "..."
    functional_description_short.short_description = "Functional description"

    def changelist_view(self, request, extra_context=None):
        """
        Ensure there is one InventoryColumn row for each field defined
        in InventoryColumn.FIELD_CHOICES. This keeps the dictionary in sync
        even if new fields are added in code.
        """
        existing = set(InventoryColumn.objects.values_list("field_name", flat=True))
        for field_name, _label in InventoryColumn.FIELD_CHOICES:
            if field_name not in existing:
                InventoryColumn.objects.create(field_name=field_name)
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(InventorySettings)
class InventorySettingsAdmin(admin.ModelAdmin):
    """
    Singleton-like settings object that holds which columns
    are restricted to purchase admin.

    - restricted_columns: ManyToMany to InventoryColumn
      (columns visible ONLY for purchase admin).
      All remaining InventoryColumns are visible for everyone.
    """
    filter_horizontal = ("restricted_columns",)

    def has_add_permission(self, request):
        # Only one settings row is allowed.
        return InventorySettings.objects.count() == 0

    def changelist_view(self, request, extra_context=None):
        """
        When user clicks on 'Settings' in admin sidebar, always redirect
        to the single existing instance (or create it if missing),
        and make sure InventoryColumn has entries for all known fields.
        """
        qs = InventorySettings.objects.all()
        if qs.exists():
            settings_obj = qs.first()
        else:
            settings_obj = InventorySettings.objects.create()

        # Ensure InventoryColumn has one row per field from FIELD_CHOICES
        existing = set(InventoryColumn.objects.values_list("field_name", flat=True))
        for field_name, _label in InventoryColumn.FIELD_CHOICES:
            if field_name not in existing:
                InventoryColumn.objects.create(field_name=field_name)

        # Redirect to that single instance's change page
        # request.path is usually '/admin/inventory/inventorysettings/'
        return redirect(f"{request.path}{settings_obj.pk}/change/")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("code",)
    search_fields = ("code",)


@admin.register(ItemGroup)
class ItemGroupAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
