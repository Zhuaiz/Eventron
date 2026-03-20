"""Reusable test data builders.

All factories return plain dicts (not ORM objects) for use in unit tests.
Integration tests can pass these to repository .create() methods.
"""

import uuid


def make_attendee(**overrides) -> dict:
    """Build an attendee data dict with sensible defaults."""
    defaults = {
        "id": str(uuid.uuid4()),
        "name": "张三",
        "title": "总经理",
        "organization": "Acme Corp",
        "department": "管理层",
        "role": "参会者",
        "priority": 0,
        "phone": "13800138000",
        "email": "zhangsan@example.com",
        "status": "confirmed",
        "attrs": {},
    }
    return {**defaults, **overrides}


def make_event(**overrides) -> dict:
    """Build an event data dict with sensible defaults."""
    defaults = {
        "id": str(uuid.uuid4()),
        "name": "Annual Meeting 2026",
        "description": "年度大会",
        "venue_rows": 10,
        "venue_cols": 5,
        "layout_type": "theater",
        "status": "active",
        "config": {},
    }
    return {**defaults, **overrides}


def make_seat(**overrides) -> dict:
    """Build a single seat data dict."""
    defaults = {
        "id": str(uuid.uuid4()),
        "row_num": 1,
        "col_num": 1,
        "label": None,
        "seat_type": "normal",
        "attendee_id": None,
    }
    return {**defaults, **overrides}


def make_seat_grid(rows: int, cols: int) -> list[dict]:
    """Generate a grid of seat dicts for testing."""
    return [
        {
            "id": str(uuid.uuid4()),
            "row_num": r,
            "col_num": c,
            "label": f"{chr(64 + r)}{c}",  # A1, A2, B1, B2, ...
            "seat_type": "normal",
            "attendee_id": None,
        }
        for r in range(1, rows + 1)
        for c in range(1, cols + 1)
    ]
