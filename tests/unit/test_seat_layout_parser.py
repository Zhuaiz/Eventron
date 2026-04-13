"""Tests for the structured seat-layout Excel parser in tools/excel_io.py."""

import pytest
from io import BytesIO

from openpyxl import Workbook

from tools.excel_io import (
    _is_decoration_cell,
    _is_name_cell,
    parse_seat_layout_structured,
)


# ── Helper: create in-memory Excel bytes ────────────────────

def _make_excel(sheets: dict[str, list[list]]) -> bytes:
    """Create a minimal .xlsx from {sheet_name: [[row], ...]}."""
    wb = Workbook()
    first = True
    for name, rows in sheets.items():
        if first:
            ws = wb.active
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Cell classification tests ────────────────────────────────

class TestCellClassifiers:
    def test_decoration_cells(self):
        assert _is_decoration_cell(None) is True
        assert _is_decoration_cell("") is True
        assert _is_decoration_cell("舞台") is True
        assert _is_decoration_cell("舞           台") is True
        assert _is_decoration_cell("通\n道") is True
        assert _is_decoration_cell("背景牆") is True
        assert _is_decoration_cell("背景墙") is True
        assert _is_decoration_cell("貴賓座席") is True
        assert _is_decoration_cell("贵宾区") is True
        assert _is_decoration_cell("—") is True
        assert _is_decoration_cell("VIP") is True

    def test_not_decoration(self):
        assert _is_decoration_cell("張三") is False
        assert _is_decoration_cell("Julian Gaetner") is False
        assert _is_decoration_cell("陳 旭") is False

    def test_name_cells(self):
        assert _is_name_cell("都永海") is True
        assert _is_name_cell("陳 旭") is True
        assert _is_name_cell("Julian Gaetner") is True
        assert _is_name_cell("TANCHEEKEONG") is True

    def test_not_name_cells(self):
        assert _is_name_cell(None) is False
        assert _is_name_cell("") is False
        assert _is_name_cell("舞台") is False
        assert _is_name_cell("第一排") is False
        assert _is_name_cell("通道") is False
        assert _is_name_cell("貴賓座席") is False


# ── Structured parser tests ──────────────────────────────────

class TestParseStructured:
    def test_simple_grid(self):
        """A single sheet with names in a grid."""
        data = _make_excel({
            "观众席": [
                [None, "舞台"],
                [],
                [None, "张三", "李四", "王五"],
                [None, "赵六", "钱七", "孙八"],
            ],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        assert len(result["areas"]) == 1
        area = result["areas"][0]
        assert area["name"] == "观众席"
        assert area["role"] == "观众"
        assert area["rows"] == 2
        assert area["cols"] == 3
        assert len(area["attendees"]) == 6
        assert area["has_stage"] is True

    def test_multiple_sheets(self):
        """Multiple sheets become separate areas."""
        data = _make_excel({
            "贵宾区": [
                [None, "陈强", "葉玉如"],
                [None, "朱偉", "查毅超"],
            ],
            "观众席": [
                [None, "张三", "李四", "王五"],
                [None, "赵六", "钱七", "孙八"],
            ],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        assert len(result["areas"]) == 2
        names = [a["name"] for a in result["areas"]]
        assert "贵宾区" in names
        assert "观众席" in names

    def test_role_inference(self):
        """Roles inferred from sheet names."""
        data = _make_excel({
            "貴賓區": [["陈强", "葉玉如"]],
            "觀眾席": [["张三", "李四"]],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        roles = {a["name"]: a["role"] for a in result["areas"]}
        assert roles["贵宾区"] == "贵宾"
        assert roles["观众席"] == "观众"

    def test_aisle_detection(self):
        """Empty columns in the middle detected as aisles."""
        data = _make_excel({
            "观众席": [
                ["张三", "李四", None, None, "王五", "赵六"],
                ["钱七", "孙八", None, None, "周九", "吴十"],
            ],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        area = result["areas"][0]
        assert area["has_aisle"] is True
        assert area["cols"] == 4  # 6 total minus 2 aisle cols

    def test_dedup_warnings(self):
        """Same name in multiple sheets triggers warning."""
        data = _make_excel({
            "贵宾区": [["陈强", "葉玉如"]],
            "贵宾室": [["陈强", "朱偉"]],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        assert len(result["dedup_warnings"]) >= 1
        assert any("陈强" in w for w in result["dedup_warnings"])

    def test_position_tracking(self):
        """Attendees get correct row/col positions."""
        data = _make_excel({
            "观众席": [
                ["张三", "李四"],
                ["王五", "赵六"],
            ],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        atts = result["areas"][0]["attendees"]
        # First row
        a1 = next(a for a in atts if a["name"] == "张三")
        assert a1["row"] == 1 and a1["col"] == 1
        a2 = next(a for a in atts if a["name"] == "李四")
        assert a2["row"] == 1 and a2["col"] == 2
        # Second row
        a3 = next(a for a in atts if a["name"] == "王五")
        assert a3["row"] == 2 and a3["col"] == 1

    def test_skip_readme_sheets(self):
        """Sheets named 说明/readme are skipped."""
        data = _make_excel({
            "观众席": [["张三", "李四"]],
            "说明": [["这是说明文档", "不要导入"]],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        assert len(result["areas"]) == 1

    def test_empty_sheet_skipped(self):
        """Empty sheets are skipped."""
        data = _make_excel({
            "观众席": [["张三"]],
            "空白": [[], [], []],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        assert len(result["areas"]) == 1

    def test_stage_position(self):
        """Stage at top vs bottom detection."""
        # Stage at top (before names)
        data = _make_excel({
            "观众席": [
                [None, "舞台"],
                [],
                ["张三", "李四"],
            ],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        assert result["areas"][0]["stage_position"] == "top"

    def test_name_cleaning(self):
        """Names with spaces are cleaned (CJK spaces removed)."""
        data = _make_excel({
            "贵宾区": [["陳 旭", "吳 薩"]],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        names = [a["name"] for a in result["areas"][0]["attendees"]]
        assert "陳旭" in names
        assert "吳薩" in names

    def test_western_names_preserved(self):
        """Western names keep their spaces."""
        data = _make_excel({
            "观众席": [["Julian Gaetner", "Daniel Sherlock"]],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        names = [a["name"] for a in result["areas"][0]["attendees"]]
        assert "Julian Gaetner" in names

    def test_total_counts(self):
        """Total attendee and seat counts are correct."""
        data = _make_excel({
            "A": [["张三", "李四"], ["王五", None]],
            "B": [["赵六"]],
        })
        result = parse_seat_layout_structured(file_bytes=data)
        assert result["total_attendees"] == 4
