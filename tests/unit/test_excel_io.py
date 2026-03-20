"""Unit tests for Excel import/export — no DB, uses in-memory bytes."""

import pytest

from tools.excel_io import (
    export_attendees_to_excel,
    export_seatmap_to_excel,
    import_attendees_from_excel,
)


def _make_excel_bytes(headers: list[str], rows: list[list]) -> bytes:
    """Helper: create a minimal .xlsx in memory."""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestImportAttendees:
    """Tests for import_attendees_from_excel."""

    def test_import_chinese_headers(self):
        """Standard Chinese header mapping."""
        data = _make_excel_bytes(
            ["姓名", "职位", "公司", "部门", "角色"],
            [["张三", "CEO", "Acme", "管理层", "vip"]],
        )
        result = import_attendees_from_excel(file_bytes=data)
        assert len(result) == 1
        assert result[0]["name"] == "张三"
        assert result[0]["title"] == "CEO"

    def test_import_english_headers(self):
        """English header mapping."""
        data = _make_excel_bytes(
            ["Name", "Title", "Organization"],
            [["Alice", "CTO", "Corp"]],
        )
        result = import_attendees_from_excel(file_bytes=data)
        assert result[0]["name"] == "Alice"
        assert result[0]["organization"] == "Corp"

    def test_skip_empty_rows(self):
        """Empty rows should be skipped."""
        data = _make_excel_bytes(
            ["姓名"],
            [["张三"], [None], ["李四"]],
        )
        result = import_attendees_from_excel(file_bytes=data)
        assert len(result) == 2

    def test_missing_name_column_raises(self):
        """Excel without name column should raise."""
        data = _make_excel_bytes(["职位"], [["CEO"]])
        with pytest.raises(ValueError, match="name"):
            import_attendees_from_excel(file_bytes=data)

    def test_no_data_rows_raises(self):
        """Header-only Excel should raise."""
        data = _make_excel_bytes(["姓名"], [])
        with pytest.raises(ValueError, match="at least one data row"):
            import_attendees_from_excel(file_bytes=data)

    def test_no_input_raises(self):
        """Neither path nor bytes should raise."""
        with pytest.raises(ValueError):
            import_attendees_from_excel()


class TestExportAttendees:
    """Tests for export_attendees_to_excel."""

    def test_export_basic(self):
        """Export produces valid xlsx bytes."""
        attendees = [{"name": "张三", "title": "CEO", "role": "甲方嘉宾"}]
        result = export_attendees_to_excel(attendees)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_export_with_seats(self):
        """Export includes seat info when provided."""
        attendees = [{"id": "a1", "name": "张三"}]
        seats = [{"attendee_id": "a1", "label": "A1", "row_num": 1, "col_num": 1}]
        result = export_attendees_to_excel(attendees, seats=seats)
        assert isinstance(result, bytes)

    def test_roundtrip(self):
        """Export then import should preserve names."""
        attendees = [
            {"name": "张三", "title": "CEO", "organization": "Acme",
             "department": "管理", "role": "甲方嘉宾", "phone": "138", "email": "a@b.com",
             "status": "confirmed"},
        ]
        xlsx_bytes = export_attendees_to_excel(attendees)
        imported = import_attendees_from_excel(file_bytes=xlsx_bytes)
        assert imported[0]["name"] == "张三"


class TestExportSeatmap:
    """Tests for export_seatmap_to_excel."""

    def test_export_grid(self):
        """Generates a valid xlsx for a 2x2 grid."""
        seats = [
            {"row_num": 1, "col_num": 1, "seat_type": "normal", "attendee_name": "张三"},
            {"row_num": 1, "col_num": 2, "seat_type": "normal", "attendee_name": None},
            {"row_num": 2, "col_num": 1, "seat_type": "disabled", "attendee_name": None},
            {"row_num": 2, "col_num": 2, "seat_type": "normal", "attendee_name": "李四"},
        ]
        result = export_seatmap_to_excel(seats, rows=2, cols=2)
        assert isinstance(result, bytes)
        assert len(result) > 0
