from django.db import models
from django.conf import settings


# Condition status for each inventory item
CONDITION_STATUS_CHOICES = [
    ("NEW", "NEW"),
    ("USED_OK", "USED / OK"),
    ("USED_NOK", "USED / NOK"),
    ("INCOMPLETE", "INCOMPLETE"),
    ("UNKNOWN", "UNKNOWN"),
    ("OTHER", "OTHER"),
]

# Favorite colors for per-user meta (star states)
FAVORITE_COLOR_CHOICES = [
    ("NONE", "None"),
    ("RED", "Red"),
    ("GREEN", "Green"),
    ("YELLOW", "Yellow"),
    ("BLUE", "Blue"),
]


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
    # Some descriptions from the import can exceed 255 chars (e.g. long adhesive specs),
    # so use TextField to avoid truncation/import errors.
    part_description = models.TextField("Part Description")
    part_number = models.CharField("Part Number", max_length=100, blank=True)
    dcm_number = models.CharField("DCM NUMBER", max_length=100, blank=True)
    oem_name = models.CharField("OEM Name", max_length=100, blank=True)
    oem_number = models.CharField("OEM Number", max_length=100, blank=True)
    vendor = models.CharField("Vendor", max_length=100, blank=True)
    source_location = models.CharField("Source Location", max_length=100, blank=True)
    units = models.CharField("Units", max_length=50, blank=True)
    unit = models.ForeignKey(
        "Unit",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="items",
    )

    quantity_in_stock = models.IntegerField("Quantity in Stock", blank=True, null=True)
    price = models.DecimalField(
        "Price",
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )
    reorder_level = models.IntegerField("Reorder Level", blank=True, null=True)
    reorder_time_days = models.IntegerField(
        "Reorder Time in Days",
        blank=True,
        null=True,
    )
    quantity_in_reorder = models.IntegerField(
        "Quantity in Reorder",
        blank=True,
        null=True,
    )
    discontinued = models.BooleanField("Discontinued?", default=False)

    # Record needs verification flag
    verify = models.BooleanField("Needs verification?", default=False)

    # Condition status field with fixed set of choices
    condition_status = models.CharField(
        "Condition Status",
        max_length=20,
        choices=CONDITION_STATUS_CHOICES,
        blank=True,
        null=True,
    )

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
    Represents a single logical column in the InventoryItem table.

    field_name         – technical name of the field in InventoryItem / UI
    short_label        – short label used in the table header (e.g. 'R', 'S', 'B')
    full_label         – full column name used in tooltips / lollipops
    functional_description – explanation of what this column means and how it behaves
    """

    FIELD_CHOICES = [
        ("location", "Location (header)"),
        ("group", "Group (FK)"),
        ("name", "Name"),
        ("part_description", "Part Description"),
        ("part_number", "Part Number"),
        ("dcm_number", "DCM Number"),
        ("oem_name", "OEM Name"),
        ("oem_number", "OEM Number"),
        ("vendor", "Vendor"),
        ("source_location", "Source Location"),
        ("unit", "Unit (FK)"),
        ("quantity_in_stock", "Quantity in Stock"),
        ("price", "Price"),
        ("reorder_level", "Reorder Level"),
        ("reorder_time_days", "Reorder Time in Days"),
        ("quantity_in_reorder", "Quantity in Reorder"),
        ("condition_status", "Condition Status"),
        ("discontinued", "Discontinued"),
        ("verify", "Verify / To Review"),
        ("favorite", "User Favorite"),
        ("note", "User Note"),
        ("for_reorder", "For Reorder (computed)"),
    ]

    field_name = models.CharField(
        max_length=50,
        unique=True,
        choices=FIELD_CHOICES,
    )

    short_label = models.CharField(
        max_length=32,
        blank=True,
        help_text="Short label for table header (e.g. 'R', 'S', 'B', 'RT'). "
                  "If empty, the default human-readable name from FIELD_CHOICES is used.",
    )

    full_label = models.CharField(
        max_length=128,
        blank=True,
        help_text="Full column name for tooltips / lollipops. "
                  "If empty, the default human-readable name from FIELD_CHOICES is used.",
    )

    functional_description = models.TextField(
        blank=True,
        help_text="Functional description for this column: what it means, "
                  "how it is edited (inline / dropdown / modal) and what it affects.",
    )

    def __str__(self) -> str:
        # Prefer full_label if provided, then short_label, then verbose from FIELD_CHOICES
        if self.full_label:
            return self.full_label
        if self.short_label:
            return self.short_label
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
        help_text=(
            "Columns visible only for purchase admin. "
            "Others are visible for everyone."
        ),
    )

    class Meta:
        verbose_name = "Column Access"
        verbose_name_plural = "Column Access"

    def __str__(self) -> str:
        return "Inventory settings"


class Unit(models.Model):
    code = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name = "Unit of Measure"
        verbose_name_plural = "Units of Measure"

    def __str__(self) -> str:
        return self.code


from django.db.models.signals import post_migrate  # noqa: E402  (kept here on purpose)


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
        verbose_name = "Group of Items"
        verbose_name_plural = "Groups of Items"

    def __str__(self) -> str:
        return self.name


class InventoryUserMeta(models.Model):
    """
    Per-user metadata for a given inventory item:
    - favorite_color: per-user star color
    - note: per-user rich text note (HTML)
    Both are visible only to that user on the frontend.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="inventory_meta",
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name="user_meta",
    )

    favorite_color = models.CharField(
        max_length=10,
        choices=FAVORITE_COLOR_CHOICES,
        default="NONE",
    )

    note = models.TextField(
        "User note",
        blank=True,
    )

    class Meta:
        unique_together = ("user", "item")
        verbose_name = "Inventory user meta"
        verbose_name_plural = "Inventory user meta"

    def __str__(self) -> str:
        return f"{self.user} – {self.item} ({self.favorite_color})"
