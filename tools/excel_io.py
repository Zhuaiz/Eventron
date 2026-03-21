"""Excel import/export for attendee lists and seat maps.

Pure functions — take data in, return data out. No DB access.
"""

from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook


# ── Column mapping: Excel header → attendee field ────────────
DEFAULT_COLUMN_MAP = {
    "姓名": "name",
    "name": "name",
    "职位": "title",
    "title": "title",
    "公司": "organization",
    "organization": "organization",
    "部门": "department",
    "department": "department",
    "角色": "role",
    "role": "role",
    "电话": "phone",
    "phone": "phone",
    "邮箱": "email",
    "email": "email",
}


def import_attendees_from_excel(
    file_path: Path | None = None,
    file_bytes: bytes | None = None,
    column_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Parse an Excel file into a list of attendee dicts.

    Args:
        file_path: Path to .xlsx file (mutually exclusive with file_bytes).
        file_bytes: Raw bytes of .xlsx file.
        column_map: Custom header→field mapping. Falls back to DEFAULT_COLUMN_MAP.

    Returns:
        List of attendee dicts with normalized field names.

    Raises:
        ValueError: If neither file_path nor file_bytes is provided,
                    or if no valid rows found.
    """
    if file_path is None and file_bytes is None:
        raise ValueError("Provide either file_path or file_bytes")

    cmap = {k.lower().strip(): v for k, v in (column_map or DEFAULT_COLUMN_MAP).items()}

    if file_bytes:
        wb = load_workbook(BytesIO(file_bytes), read_only=True)
    else:
        wb = load_workbook(file_path, read_only=True)

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if len(rows) < 2:
        raise ValueError("Excel file must have a header row and at least one data row")

    # Map headers
    headers = [str(h).lower().strip() if h else "" for h in rows[0]]
    field_indices: dict[str, int] = {}
    for i, header in enumerate(headers):
        if header in cmap:
            field_indices[cmap[header]] = i

    if "name" not in field_indices:
        raise ValueError("Excel file must have a '姓名' or 'name' column")

    # Parse data rows
    attendees = []
    for row in rows[1:]:
        if not row or not any(row):
            continue
        att: dict[str, Any] = {"attrs": {}}
        for field, idx in field_indices.items():
            val = row[idx] if idx < len(row) else None
            att[field] = str(val).strip() if val is not None else None
        if att.get("name"):
            attendees.append(att)

    return attendees


def export_attendees_to_excel(
    attendees: list[dict[str, Any]],
    seats: list[dict[str, Any]] | None = None,
) -> bytes:
    """Export attendee list (optionally with seat info) to Excel bytes.

    Args:
        attendees: List of attendee dicts.
        seats: Optional list of seat dicts (matched by attendee_id).

    Returns:
        Bytes of the generated .xlsx file.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "参会人员"

    # Build seat lookup
    seat_map: dict[str, dict] = {}
    if seats:
        for s in seats:
            if s.get("attendee_id"):
                seat_map[s["attendee_id"]] = s

    # Headers
    headers = ["姓名", "职位", "公司", "部门", "角色", "电话", "邮箱", "状态"]
    if seats:
        headers.extend(["座位号", "排", "列"])
    ws.append(headers)

    # Data rows
    for att in attendees:
        row = [
            att.get("name", ""),
            att.get("title", ""),
            att.get("organization", ""),
            att.get("department", ""),
            att.get("role", ""),
            att.get("phone", ""),
            att.get("email", ""),
            att.get("status", ""),
        ]
        if seats:
            seat = seat_map.get(att.get("id", ""), {})
            row.extend([
                seat.get("label", ""),
                seat.get("row_num", ""),
                seat.get("col_num", ""),
            ])
        ws.append(row)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_seatmap_to_excel(
    seats: list[dict[str, Any]],
    rows: int,
    cols: int,
) -> bytes:
    """Export a visual seat map grid to Excel.

    Each cell shows the attendee name or '空' for empty seats.

    Args:
        seats: List of seat dicts with row_num, col_num, and optional attendee_name.
        rows: Total rows in venue.
        cols: Total cols in venue.

    Returns:
        Bytes of the generated .xlsx file.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "座位图"

    # Build lookup
    seat_map: dict[tuple[int, int], dict] = {}
    for s in seats:
        seat_map[(s["row_num"], s["col_num"])] = s

    # Header row (column numbers)
    ws.append([""] + [f"列{c}" for c in range(1, cols + 1)])

    # Data rows
    for r in range(1, rows + 1):
        row = [f"第{r}排"]
        for c in range(1, cols + 1):
            s = seat_map.get((r, c), {})
            if s.get("seat_type") in ("disabled", "aisle"):
                row.append("—")
            elif s.get("attendee_name"):
                row.append(s["attendee_name"])
            else:
                row.append("空")
        ws.append(row)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_excel_sheets_as_text(
    file_path: Path | None = None,
    file_bytes: bytes | None = None,
    *,
    max_rows_per_sheet: int = 30,
) -> str:
    """Read all sheets from an Excel file and format as plain text.

    Returns a human-readable summary suitable for LLM analysis.
    Each sheet is shown with its name, dimensions, and first N rows.
    """
    if file_path is None and file_bytes is None:
        raise ValueError("Provide either file_path or file_bytes")

    if file_bytes:
        wb = load_workbook(BytesIO(file_bytes), read_only=True)
    else:
        wb = load_workbook(file_path, read_only=True)

    parts: list[str] = []
    for ws_sheet in wb.worksheets:
        title = ws_sheet.title or "Sheet"
        rows = list(ws_sheet.iter_rows(values_only=True))
        total = len(rows)
        parts.append(f"=== Sheet: {title} ({total} rows) ===")
        for i, row in enumerate(rows[:max_rows_per_sheet]):
            cells = [str(c) if c is not None else "" for c in row]
            # Trim trailing empty cells
            while cells and not cells[-1]:
                cells.pop()
            parts.append(f"  Row {i+1}: [{', '.join(cells)}]")
        if total > max_rows_per_sheet:
            parts.append(f"  ... ({total - max_rows_per_sheet} more rows)")
        parts.append("")

    wb.close()
    return "\n".join(parts)


def _is_label_cell(val: Any) -> bool:
    """Check if a cell value looks like a row label rather than a seat."""
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    # Common row labels: "第1排", "A排", "排号", "Row 1", numbers alone
    low = s.lower()
    if any(kw in low for kw in ["排", "row", "列", "col", "座位", "编号"]):
        return True
    # Single letter (like "A", "B" used as row prefix)
    if len(s) == 1 and s.isalpha():
        return True
    return False


def _count_seats_in_row(cells: tuple | list) -> int:
    """Count non-empty cells in a row, skipping the first label column.

    Uses a two-pass approach:
    1. Check if the first cell looks like a row label → skip it
    2. Count remaining non-empty cells
    """
    if not cells:
        return 0

    data_start = 0
    first = cells[0]
    if first is not None:
        s = str(first).strip()
        # Skip if it's a row label: pure text with no digits, or label-like
        if _is_label_cell(first):
            data_start = 1
        elif isinstance(first, str) and len(s) <= 4 and not any(
            c.isdigit() for c in s
        ):
            data_start = 1  # short non-numeric text = likely label

    return sum(
        1 for c in cells[data_start:]
        if c is not None and str(c).strip()
    )


def parse_seat_layout_from_excel(
    file_path: Path | None = None,
    file_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    """Parse an Excel file into row_specs for generate_custom_layout.

    Each sheet = one zone (sheet name = zone label).
    Each data row = one seating row. Non-empty cells = seats.
    Header rows and noise rows (≤2 seats) are auto-filtered.

    Returns:
        List of row_spec dicts: [{count, repeat?, zone?}]
        compatible with generate_custom_layout().
    """
    if file_path is None and file_bytes is None:
        raise ValueError("Provide either file_path or file_bytes")

    if file_bytes:
        wb = load_workbook(BytesIO(file_bytes), read_only=True)
    else:
        wb = load_workbook(file_path, read_only=True)

    all_specs: list[dict[str, Any]] = []

    for ws_sheet in wb.worksheets:
        zone_name = ws_sheet.title.strip() if ws_sheet.title else None
        # Skip non-seat sheets
        if zone_name and any(
            kw in zone_name.lower()
            for kw in ["说明", "readme", "注意", "instruction"]
        ):
            continue

        rows_data = list(ws_sheet.iter_rows(values_only=True))
        if not rows_data:
            continue

        # --- Pass 1: count seats per row, skip header ---
        raw_counts: list[int] = []
        # Detect header: first row where all non-empty cells are text labels
        start_idx = 0
        has_label_col = False  # if header detected, first col is labels
        first_row = rows_data[0]
        if first_row:
            non_empty = [c for c in first_row if c is not None and str(c).strip()]
            if non_empty and all(isinstance(c, str) for c in non_empty):
                joined = " ".join(str(c).lower() for c in non_empty)
                if any(kw in joined for kw in [
                    "排", "row", "列", "col", "座", "seat", "编号", "号",
                ]):
                    start_idx = 1
                    has_label_col = True  # first col is row labels

        for row in rows_data[start_idx:]:
            if has_label_col:
                # Skip column 0 (row label) for all data rows
                cells = list(row)[1:]
                cnt = sum(1 for c in cells if c is not None and str(c).strip())
            else:
                cnt = _count_seats_in_row(row)
            raw_counts.append(cnt)

        if not raw_counts:
            continue

        # --- Pass 2: determine minimum seat threshold ---
        # Use the median count to filter noise rows (labels, spacers)
        sorted_counts = sorted(c for c in raw_counts if c > 0)
        if not sorted_counts:
            continue
        median = sorted_counts[len(sorted_counts) // 2]
        # Threshold: at least 30% of median, minimum 3 seats
        threshold = max(3, int(median * 0.3))

        # --- Pass 3: group consecutive rows by count ---
        prev_count = -1
        repeat = 0

        for cnt in raw_counts:
            if cnt < threshold:
                continue  # skip noise rows

            if cnt == prev_count:
                repeat += 1
            else:
                if prev_count > 0:
                    spec: dict[str, Any] = {
                        "count": prev_count,
                        "repeat": repeat,
                    }
                    if zone_name:
                        spec["zone"] = zone_name
                    all_specs.append(spec)
                prev_count = cnt
                repeat = 1

        # Flush last group
        if prev_count > 0:
            spec = {"count": prev_count, "repeat": repeat}
            if zone_name:
                spec["zone"] = zone_name
            all_specs.append(spec)

    wb.close()
    return all_specs
