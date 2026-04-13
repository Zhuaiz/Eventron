"""Tests for tools/chinese_norm.py — T→S normalization for event terms."""

import pytest

from tools.chinese_norm import (
    clean_name,
    infer_role_from_area_name,
    normalize_event_term,
    normalize_role,
    normalize_zone,
)


# ── normalize_event_term ─────────────────────────────────────

class TestNormalizeEventTerm:
    def test_basic_terms(self):
        assert normalize_event_term("觀眾席") == "观众席"
        assert normalize_event_term("貴賓區") == "贵宾区"
        assert normalize_event_term("貴賓室") == "贵宾室"

    def test_role_terms(self):
        assert normalize_event_term("工作人員") == "工作人员"
        assert normalize_event_term("參會者") == "参会者"
        assert normalize_event_term("演講嘉賓") == "演讲嘉宾"

    def test_venue_terms(self):
        assert normalize_event_term("會場") == "会场"
        assert normalize_event_term("舞臺") == "舞台"
        assert normalize_event_term("背景牆") == "背景墙"
        assert normalize_event_term("簽到") == "签到"

    def test_already_simplified(self):
        assert normalize_event_term("观众席") == "观众席"
        assert normalize_event_term("贵宾区") == "贵宾区"

    def test_empty_and_whitespace(self):
        assert normalize_event_term("") == ""
        assert normalize_event_term("  ") == ""

    def test_mixed_content(self):
        # Partial traditional characters
        assert normalize_event_term("觀眾区") == "观众区"

    def test_strips_whitespace(self):
        assert normalize_event_term("  觀眾席  ") == "观众席"


# ── normalize_role ───────────────────────────────────────────

class TestNormalizeRole:
    def test_traditional_roles(self):
        assert normalize_role("觀眾") == "观众"
        assert normalize_role("貴賓") == "贵宾"

    def test_none_and_empty(self):
        assert normalize_role(None) == "参会者"
        assert normalize_role("") == "参会者"
        assert normalize_role("  ") == "参会者"

    def test_already_simplified(self):
        assert normalize_role("贵宾") == "贵宾"
        assert normalize_role("观众") == "观众"


# ── normalize_zone ───────────────────────────────────────────

class TestNormalizeZone:
    def test_traditional_zones(self):
        assert normalize_zone("貴賓區") == "贵宾区"
        assert normalize_zone("觀眾席") == "观众席"

    def test_none_and_empty(self):
        assert normalize_zone(None) is None
        assert normalize_zone("") is None
        assert normalize_zone("  ") is None


# ── infer_role_from_area_name ────────────────────────────────

class TestInferRole:
    def test_vip_areas(self):
        assert infer_role_from_area_name("貴賓區") == "贵宾"
        assert infer_role_from_area_name("贵宾区") == "贵宾"
        assert infer_role_from_area_name("VIP Room") == "贵宾"
        assert infer_role_from_area_name("貴賓室") == "贵宾"

    def test_audience_areas(self):
        assert infer_role_from_area_name("觀眾席") == "观众"
        assert infer_role_from_area_name("观众席") == "观众"

    def test_guest_areas(self):
        assert infer_role_from_area_name("嘉賓區") == "嘉宾"
        assert infer_role_from_area_name("嘉宾席") == "嘉宾"

    def test_staff_areas(self):
        assert infer_role_from_area_name("工作人員區") == "工作人员"
        assert infer_role_from_area_name("Staff Area") == "工作人员"

    def test_speaker_areas(self):
        assert infer_role_from_area_name("演講嘉賓席") == "演讲嘉宾"

    def test_fallback(self):
        assert infer_role_from_area_name("区域A") == "参会者"
        assert infer_role_from_area_name("Section 1") == "参会者"


# ── clean_name ───────────────────────────────────────────────

class TestCleanName:
    def test_cjk_name_with_spaces(self):
        assert clean_name("陳 旭") == "陳旭"
        assert clean_name("吳 薩") == "吳薩"

    def test_western_name_preserved(self):
        assert clean_name("Julian Gaetner") == "Julian Gaetner"
        assert clean_name("Daniel Sherlock") == "Daniel Sherlock"

    def test_western_name_extra_spaces(self):
        assert clean_name("  Julian  Gaetner  ") == "Julian Gaetner"

    def test_none_and_empty(self):
        assert clean_name(None) is None
        assert clean_name("") is None
        assert clean_name("  ") is None

    def test_no_t2s_conversion(self):
        # Names should NOT be converted
        assert clean_name("陳旭") == "陳旭"  # Traditional preserved
        assert clean_name("張曼莉") == "張曼莉"

    def test_mixed_cjk_english(self):
        # Mostly CJK → remove spaces
        assert clean_name("TAN CHEE KEONG") == "TAN CHEE KEONG"
