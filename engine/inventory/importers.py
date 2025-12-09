import pandas as pd
from decimal import Decimal, InvalidOperation
from django.db import transaction
from .models import InventoryItem, Unit


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

    # 1) Read file (CSV or Excel) very defensively (no header)
    name = getattr(excel_file, "name", "").lower()
    df = None

    def reset_file(f):
        if hasattr(f, "seek"):
            try:
                f.seek(0)
            except Exception:
                pass

    if name.endswith(".csv"):
        # Try multiple separators, header=None to keep all rows for header detection
        for sep in [",", ";", "\t", "|"]:
            reset_file(excel_file)
            try:
                tmp = pd.read_csv(excel_file, sep=sep, header=None, dtype=str)
                if tmp.shape[1] > 1 or not tmp.empty:
                    df = tmp
                    break
            except Exception:
                continue
        if df is None:
            reset_file(excel_file)
            df = pd.read_csv(excel_file, sep=None, engine="python", header=None, dtype=str)
    else:
        try:
            df = pd.read_excel(excel_file, sheet_name="Inventory List", header=None, dtype=str)
        except Exception:
            reset_file(excel_file)
            try:
                df = pd.read_excel(excel_file, header=None, dtype=str)
            except Exception:
                reset_file(excel_file)
                df = pd.read_excel(excel_file, dtype=str)

    # Drop columns that are completely empty
    df = df.dropna(axis=1, how="all")

    # Detect header row: find the first row containing any of expected header tokens
    expected_tokens = {"localization", "localisation", "location", "for reorder", "group", "name"}
    header_idx = None
    for idx, row in df.iterrows():
        values = [str(v).strip().lower() for v in row.tolist()]
        if any(tok in values for tok in expected_tokens):
            header_idx = idx
            break

    if header_idx is None:
        # fallback: assume first non-empty row is header
        header_idx = 0

    header_row = df.iloc[header_idx]
    df_data = df.iloc[header_idx + 1 :].copy()
    df_data.columns = header_row.values

    # After header assignment, drop columns that remain completely empty
    df_data = df_data.dropna(axis=1, how="all")

    created = 0
    skipped = 0
    missing_loc = 0
    rack_invalid = 0

    # Map normalized column names -> actual columns in the file
    colmap = {str(c).strip().lower(): c for c in df_data.columns}

    def get_value(row, candidates):
        """
        Fetch value from row using a list of candidate column names (case/space-insensitive).
        """
        for cand in candidates:
            key = cand.strip().lower()
            if key in colmap:
                return row.get(colmap[key])
        return None

    def parse_loc(loc_value):
        """
        Parse 'Localization' into rack, shelf, box.
        Expected format examples:
        '1-B-1', '10-A', '10-C-5-12', '12-A-1/3', '10-D-1-BK'.
        Rule:
        - first token -> rack (int if possible)
        - second token (if present) -> shelf
        - rest (if any) joined with '-' -> box
        """
        if pd.isna(loc_value):
            return None, None, None

        text = str(loc_value).strip()
        if not text:
            return None, None, None

        parts = text.split("-")
        if not parts:
            return None, None, None

        rack_str = parts[0]
        shelf_str = parts[1] if len(parts) > 1 else "0"
        # if no explicit box provided, default to "0"
        box_str = "-".join(parts[2:]) if len(parts) > 2 else "0"

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
        nonlocal created, skipped, missing_loc, rack_invalid

        # Preload existing unit codes for quick lookup
        unit_by_code = {u.code.upper(): u for u in Unit.objects.all()}

        for _, row in df_data.iterrows():
            rack, shelf, box = parse_loc(row.get("Localization"))
            if rack is None and "localization" not in colmap:
                # Try alternative column names for location
                loc_val = get_value(row, ["localization", "location", "localisation", "lokalizacja"])
                rack, shelf, box = parse_loc(loc_val)

            # If localization is invalid or missing, skip the row
            if rack is None:
                loc_raw = row.get("Localization")
                if pd.isna(loc_raw):
                    missing_loc += 1
                else:
                    rack_invalid += 1
                skipped += 1
                continue

            raw_unit = get_value(row, ["units", "unit"])
            canonical_unit, raw_upper = normalize_unit(raw_unit)
            unit_fk = unit_by_code.get(canonical_unit)

            InventoryItem.objects.create(
                rack=rack,
                shelf=shelf,
                box=box,
                group_name=get_value(row, ["group", "grupa"]) or "",
                name=get_value(row, ["name"]) or "",
                part_description=get_value(row, ["part description", "description"]) or "",
                part_number=get_value(row, ["part number"]) or "",
                dcm_number=get_value(row, ["dcm number"]) or "",
                oem_name=get_value(row, ["oem name"]) or "",
                oem_number=get_value(row, ["oem number"]) or "",
                vendor=get_value(row, ["vendor"]) or "",
                source_location=get_value(row, ["source location", "source"]) or "",
                units=canonical_unit or (raw_upper or ""),
                unit=unit_fk,
                quantity_in_stock=parse_int(get_value(row, ["quantity in stock", "qty in stock", "stock quantity"])),
                price=parse_decimal(get_value(row, ["price", "unit price"])),
                reorder_level=parse_int(get_value(row, ["reorder level"])),
                reorder_time_days=parse_int(get_value(row, ["reorder time in days", "reorder time", "rt"])),
                quantity_in_reorder=parse_int(get_value(row, ["quantity in reorder", "reorder quantity"])),
                discontinued=parse_bool_discontinued(get_value(row, ["discontinued?", "discontinued", "disc"])),
            )

            created += 1

    _do_import()

    return {
        "created": created,
        "skipped": skipped,
        "missing_loc": missing_loc,
        "rack_invalid": rack_invalid,
        "columns": list(df_data.columns),
        "total_rows": len(df_data),
    }

# Helper to normalise unit names from import to our canonical codes
UNIT_SYNONYMS = {
    "ROLL": ["ROLL", "ROLLS"],
    "M": ["M", "METER", "METERS"],
    "CM": ["CM"],
    "MM": ["MM"],
    "LTR": ["LTR", "LITRE", "LITRES", "LITER", "LITERS"],
    "ML": ["ML"],
    "PCS": ["PCS", "PC", "PIECE", "PIECES"],
    "PAIR": ["PAIR", "PAIRS"],
    "SET": ["SET", "SETS"],
    "KIT": ["KIT", "KITS"],
    "ORGANISER": ["ORGANISER", "ORGANIZER"],
    "BOX": ["BOX", "BOXES"],
    "CAN": ["CAN", "CANS"],
    "KGM": ["KGM", "KG", "KGS", "KILOGRAM", "KILOGRAMS"],
    "METER": ["METER", "METERS"],
}

def normalize_unit(raw):
    if raw is None:
        return None, None
    if pd.isna(raw):
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    upper = text.upper()
    for canonical, aliases in UNIT_SYNONYMS.items():
        if upper == canonical or upper in aliases:
            return canonical, upper
    return upper, upper
