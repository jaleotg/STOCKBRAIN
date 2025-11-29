from django.contrib import admin, messages
from django.shortcuts import redirect
from .models import InventoryItem, InventoryColumn, InventorySettings
from .importers import import_inventory_from_excel
from .models import InventoryItem, InventoryColumn, InventorySettings, Unit, ItemGroup




class InventoryImportExport(InventoryItem):
    """
    Proxy model used only to show a separate 'Import/Export' entry
    in the admin sidebar, under the Inventory app.
    """

    class Meta:
        proxy = True
        verbose_name = "Import/Export"
        verbose_name_plural = "Import/Export"


@admin.register(InventoryImportExport)
class InventoryImportExportAdmin(admin.ModelAdmin):
    """
    Admin view for the Import/Export menu entry.

    We use a custom change_list_template which will show:
    - an upload field + Import button
    - an Export button (currently not implemented)
    """

    change_list_template = "admin/inventory_import_export.html"

    def has_add_permission(self, request):
        # We don't add instances of the proxy model.
        return False

    def has_delete_permission(self, request, obj=None):
        # We don't delete instances of the proxy model.
        return False

    def changelist_view(self, request, extra_context=None):
        """
        Handles the Import form submit (POST with file)
        and renders the Import/Export page.
        """
        if request.method == "POST" and request.FILES.get("file"):
            excel_file = request.FILES["file"]

            try:
                stats = import_inventory_from_excel(excel_file)
                created = stats.get("created", 0)
                skipped = stats.get("skipped", 0)
                messages.success(
                    request,
                    f"Import completed. Created {created} items, skipped {skipped} rows without valid localization.",
                )
            except Exception as exc:
                messages.error(request, f"Import failed: {exc}")

            # Always redirect after POST to avoid resubmission
            return redirect(request.path)

        extra_context = extra_context or {}
        extra_context["export_message"] = "Export is not implemented yet."

        return super().changelist_view(request, extra_context=extra_context)
@admin.register(InventorySettings)
class InventorySettingsAdmin(admin.ModelAdmin):
    """
    Admin menu 'Settings'.

    We do NOT show the changelist with a table.
    When user clicks 'Settings' in the sidebar, we immediately redirect
    to the edit form of the single InventorySettings instance.

    The field 'restricted_columns' is a many-to-many dual list
    (available / chosen).
    """

    filter_horizontal = ("restricted_columns",)

    def has_add_permission(self, request):
        """
        We want exactly ONE settings row.
        If it exists, do not allow creating another.
        """
        if InventorySettings.objects.exists():
            return False
        return super().has_add_permission(request)

    def changelist_view(self, request, extra_context=None):
        """
        Instead of showing the list 'Select Settings to change',
        we redirect straight to the single settings object's change view.
        Also, we ensure that:
        - exactly one InventorySettings instance exists
        - InventoryColumn objects exist for all FIELD_CHOICES
        """

        # Ensure there is exactly one settings instance
        qs = InventorySettings.objects.all()
        if qs.exists():
            settings_obj = qs.first()
        else:
            settings_obj = InventorySettings.objects.create()

        # Ensure InventoryColumn objects for all FIELD_CHOICES
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
