from django.db import models


class InventoryItem(models.Model):
    # Localization split into 3 columns
    rack = models.IntegerField()
    shelf = models.CharField(max_length=1)          # always store uppercase
    box = models.CharField(max_length=50)           # number or any text

    # Columns based on Excel
    group_name = models.CharField("Group", max_length=100)
    group = models.ForeignKey(
        "ItemGroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="items",
    )

    name = models.CharField("Name", max_length=100)
    part_description = models.CharField("Part Description", max_length=255)
    part_number = models.CharField("Part Number", max_length=100, blank=True)
    dcm_number = models.CharField("DCM NUMBER", max_length=100, blank=True)
    oem_name = models.CharField("OEM Name", max_length=100, blank=True)
    oem_number = models.CharField("OEM Number", max_length=100, blank=True)
    vendor = models.CharField("Vendor", max_length=100, blank=True)
    source_location = models.CharField("Source Location", max_length=100, blank=True)
    units = models.CharField("Units", max_length=50, blank=True)
    unit = models.ForeignKey("Unit", null=True, blank=True, on_delete=models.SET_NULL, related_name="items",)

    quantity_in_stock = models.IntegerField("Quantity in Stock", blank=True, null=True)
    price = models.DecimalField("Price", max_digits=10, decimal_places=2,
                                blank=True, null=True)
    reorder_level = models.IntegerField("Reorder Level", blank=True, null=True)
    reorder_time_days = models.IntegerField("Reorder Time in Days", blank=True, null=True)
    quantity_in_reorder = models.IntegerField("Quantity in Reorder", blank=True, null=True)
    discontinued = models.BooleanField("Discontinued?", default=False)

    class Meta:
        ordering = ["rack", "shelf", "box"]

    def __str__(self):
        return f"{self.localization_str} - {self.part_description}"

    @property
    def localization_str(self) -> str:
        """Rebuild 8--A--1 style string if you ever need it."""
        return f"{self.rack}--{self.shelf.upper()}--{self.box}"

    @property
    def for_reorder(self) -> bool:
        """
        Computed flag: DO NOT store in DB.
        True when quantity_in_stock <= reorder_level and not discontinued.
        """
        if (
            self.quantity_in_stock is not None
            and self.reorder_level is not None
            and not self.discontinued
        ):
            return self.quantity_in_stock <= self.reorder_level
        return False

    def save(self, *args, **kwargs):
        # Always keep shelf uppercase
        if self.shelf:
            self.shelf = self.shelf.upper()
        super().save(*args, **kwargs)
class InventoryColumn(models.Model):
    """
    Represents a logical column from InventoryItem that can be restricted
    to purchase admin only.

    We EXCLUDE from here:
    - rack, shelf, box
    - group_name, name, part_description, part_number
    - units, quantity_in_stock
    because they are always visible for everyone.
    """

    FIELD_CHOICES = [
        ("dcm_number", "DCM NUMBER"),
        ("oem_name", "OEM Name"),
        ("oem_number", "OEM Number"),
        ("vendor", "Vendor"),
        ("source_location", "Source Location"),
        ("price", "Price"),
        ("reorder_level", "Reorder Level"),
        ("reorder_time_days", "Reorder Time in Days"),
        ("quantity_in_reorder", "Quantity in Reorder"),
        ("discontinued", "Discontinued?"),
    ]

    field_name = models.CharField(
        max_length=50,
        unique=True,
        choices=FIELD_CHOICES,
    )

    def __str__(self) -> str:
        return dict(self.FIELD_CHOICES).get(self.field_name, self.field_name)


class InventorySettings(models.Model):
    """
    Holds configuration which columns are restricted to purchase admin.
    - restricted_columns: columns visible ONLY for purchase admin.
    - the remaining columns from InventoryColumn are visible for everyone.
    """

    restricted_columns = models.ManyToManyField(
        InventoryColumn,
        blank=True,
        help_text="Columns visible only for purchase admin. Others are visible for everyone.",
    )

    class Meta:
        verbose_name = "Settings"
        verbose_name_plural = "Settings"

    def __str__(self) -> str:
        return "Inventory settings"

class Unit(models.Model):
    code = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name = "Unit"
        verbose_name_plural = "Units"

    def __str__(self) -> str:
        return self.code
from django.db.models.signals import post_migrate


DEFAULT_UNITS = [
    "PCS",
    "PAIR",
    "SET",
    "KIT",
    "ORGANISER",
    "BOX",
    "MM",
    "CM",
    "M",
    "LTR",
    "ML",
    "CAN",
    "KGM",
    "ROLL",
]


def create_default_units(sender, app_config, **kwargs):
    # This signal runs after each app is migrated.
    # We only act when it's the 'inventory' app.
    if app_config.name != "inventory":
        return

    UnitModel = app_config.get_model("Unit")
    for code in DEFAULT_UNITS:
        UnitModel.objects.get_or_create(code=code)


post_migrate.connect(create_default_units)

class ItemGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Group"
        verbose_name_plural = "Groups"

    def __str__(self) -> str:
        return self.name
