"""Structured Message Parts — typed UI cards for frontend rendering.

Each tool can return a list of MessagePart dicts alongside its text
response. The frontend renders each part type with a dedicated React
component, providing rich inline cards instead of raw markdown.

Usage in plugin handle() methods:
    return {
        "turn_output": "已创建 10×8 座位布局。",
        "parts": [
            seat_map_part(event_id, total=80, assigned=0, zones=["贵宾区"]),
        ],
    }

Usage in tools (via contextvars accumulator):
    from agents.message_parts import push_part, event_card_part
    push_part(event_card_part(event_id, name="年会"))
"""

from __future__ import annotations

import contextvars
from typing import Any

# Context var: tools can push parts here without modifying return types.
# Set by the orchestrator before running the ReAct loop.
PARTS_ACCUMULATOR: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("parts_accumulator", default=None)
)


def push_part(part: dict[str, Any]) -> None:
    """Push a UI card part to the current accumulator (if set).

    Safe to call from any tool — no-ops silently if no accumulator.
    """
    acc = PARTS_ACCUMULATOR.get(None)
    if acc is not None:
        acc.append(part)


# ── Part constructors (domain-specific) ─────────────────────────

def seat_map_part(
    event_id: str,
    *,
    total: int = 0,
    assigned: int = 0,
    unassigned: int = 0,
    zones: list[str] | None = None,
    layout_type: str = "",
) -> dict[str, Any]:
    """Inline seat map card with stats."""
    return {
        "type": "seat_map",
        "event_id": event_id,
        "stats": {
            "total": total,
            "assigned": assigned,
            "unassigned": unassigned or (total - assigned),
            "zones": zones or [],
            "layout_type": layout_type,
        },
    }


def attendee_table_part(
    rows: list[dict[str, Any]],
    *,
    total: int | None = None,
    title: str = "参会者列表",
) -> dict[str, Any]:
    """Scrollable attendee table card.

    Each row: {name, role?, organization?, seat_label?, priority?}
    """
    return {
        "type": "attendee_table",
        "title": title,
        "rows": rows[:50],  # Cap for frontend performance
        "total": total if total is not None else len(rows),
    }


def event_card_part(
    event_id: str,
    *,
    name: str = "",
    date: str = "",
    location: str = "",
    status: str = "",
    layout_type: str = "",
    attendee_count: int = 0,
    seat_count: int = 0,
) -> dict[str, Any]:
    """Event summary card."""
    return {
        "type": "event_card",
        "event": {
            "id": event_id,
            "name": name,
            "date": date,
            "location": location,
            "status": status,
            "layout_type": layout_type,
            "attendee_count": attendee_count,
            "seat_count": seat_count,
        },
    }


def page_preview_part(
    url: str,
    *,
    title: str = "签到页预览",
    description: str = "",
) -> dict[str, Any]:
    """Iframe preview card for H5 pages."""
    return {
        "type": "page_preview",
        "url": url,
        "title": title,
        "description": description,
    }


def confirmation_part(
    prompt: str,
    *,
    confirm_label: str = "确认",
    cancel_label: str = "取消",
    confirm_value: str = "确认",
    cancel_value: str = "取消",
    confirmation_id: str = "",
) -> dict[str, Any]:
    """Action confirmation card with approve/reject buttons."""
    return {
        "type": "confirmation",
        "id": confirmation_id,
        "prompt": prompt,
        "actions": [
            {
                "label": confirm_label,
                "value": confirm_value,
                "style": "primary",
            },
            {
                "label": cancel_label,
                "value": cancel_value,
                "style": "danger",
            },
        ],
    }


def file_link_part(
    url: str,
    *,
    filename: str = "",
    file_type: str = "",
    size: int = 0,
) -> dict[str, Any]:
    """Downloadable file link card."""
    return {
        "type": "file_link",
        "url": url,
        "filename": filename,
        "file_type": file_type,
        "size": size,
    }


def stats_part(
    title: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Key-value statistics card.

    Each item: {label: str, value: str|int, color?: str}
    """
    return {
        "type": "stats",
        "title": title,
        "items": items,
    }
