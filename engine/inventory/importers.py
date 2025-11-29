import pandas as pd
from decimal import Decimal, InvalidOperation
from django.db import transaction
from .models import InventoryItem


def parse_int(value):
    """Convert a value to int or return None if empty/NaN."""
    if pd.isna(value) or value == "":
        return None
    try:
        # Excel often gives floats like 3.0
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse_decimal(value):
    """Convert a value to Decimal or return None if empty/NaN."""
    if pd.isna(value) or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    # In case decimal comma appears
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def import_inventory_from_excel(excel_file):
    """
    Import inventory data from the Excel file.

    Assumptions based on the current INVENTORY-DCM-current.xlsm:
    - Sheet name: 'Inventory List'
    - There are extra header rows.
    - The row containing column names is inside the sheet (with values like
      'For Reorder', 'Localization', 'Group', 'Name', etc.).
    """

    # 1) Read the sheet with an offset header
    df = pd.read_excel(excel_file, sheet_name="Inventory List", header=1)

    # 2) First row in this DataFrame contains the "real" column names
    header_row = df.iloc[0]
    df_data = df.iloc[1:].copy()
    df_data.columns = header_row.values

    created = 0
    skipped = 0

    def parse_loc(loc_value):
        """
        Parse 'Localization' into rack, shelf, box.
        Expected format: '1-B-1' (always with '-' between R, S, B).
        """
        if pd.isna(loc_value):
            return None, None, None

        text = str(loc_value).strip()
        if not text:
            return None, None, None

        parts = text.split("-")
        if len(parts) != 3:
            return None, None, None

        rack_str, shelf_str, box_str = parts

        try:
            rack_val = int(rack_str)
        except ValueError:
            rack_val = None

        shelf_val = shelf_str.strip().upper()
        box_val = box_str.strip()

        return rack_val, shelf_val, box_val

    def parse_bool_discontinued(value):
        if pd.isna(value):
            return False
        text = str(value).strip().lower()
        return text in ["yes", "y", "1", "true", "t"]

    @transaction.atomic
    def _do_import():
        nonlocal created, skipped

        for _, row in df_data.iterrows():
            rack, shelf, box = parse_loc(row.get("Localization"))

            # If localization is invalid or missing, skip the row
            if rack is None or not shelf or not box:
                skipped += 1
                continue

            InventoryItem.objects.create(
                rack=rack,
                shelf=shelf,
                box=box,
                group_name=row.get("Group") or "",
                name=row.get("Name") or "",
                part_description=row.get("Part Description") or "",
                part_number=row.get("Part Number") or "",
                dcm_number=row.get("DCM NUMBER") or "",
                oem_name=row.get("OEM Name") or "",
                oem_number=row.get("OEM Number") or "",
                vendor=row.get("Vendor") or "",
                source_location=row.get("Source Location") or "",
                units=row.get("Units") or "",
                quantity_in_stock=parse_int(row.get("Quantity in Stock")),
                price=parse_decimal(row.get("Price")),
                reorder_level=parse_int(row.get("Reorder Level")),
                reorder_time_days=parse_int(row.get("Reorder Time in Days")),
                quantity_in_reorder=parse_int(row.get("Quantity in Reorder")),
                discontinued=parse_bool_discontinued(row.get("Discontinued?")),
            )

            created += 1

    _do_import()

    return {
        "created": created,
        "skipped": skipped,
    }
