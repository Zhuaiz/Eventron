"""Public check-in routes — NO JWT required.

These endpoints are accessed by attendees on their phones after scanning
the event QR code.  They live under ``/p/{event_id}/checkin``.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.deps import get_checkin_service, get_event_service
from app.services.checkin_service import CheckinService
from app.services.event_service import EventService
from app.services.exceptions import (
    AttendeeNotFoundError,
    EventNotFoundError,
    InvalidStateTransitionError,
)

router = APIRouter()

# ── Schemas ────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    name: str


class CandidateItem(BaseModel):
    attendee_id: str
    name: str
    title: str | None = None
    organization: str | None = None


class CheckinResult(BaseModel):
    status: str  # "success" | "already" | "ambiguous" | "not_found" | "error"
    message: str
    attendee_name: str | None = None
    seat_label: str | None = None
    seat_zone: str | None = None
    candidates: list[CandidateItem] | None = None


# ── Public page serving ────────────────────────────────────────

@router.get("/checkin", response_class=HTMLResponse)
async def serve_checkin_page(
    event_id: uuid.UUID,
    event_svc: EventService = Depends(get_event_service),
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Serve the mobile H5 check-in page for an event."""
    from tools.page_render import render_checkin_page

    try:
        event = await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="活动不存在")

    stats = await checkin_svc.get_checkin_stats(event_id)

    # Check if there's a custom checkin page deployed by the agent
    from pathlib import Path
    custom_page = Path(f"uploads/events/{event_id}/checkin_page.html")
    if custom_page.exists():
        return HTMLResponse(
            custom_page.read_text(encoding="utf-8"),
        )

    html = render_checkin_page(
        event_name=event.name,
        event_date=str(event.event_date) if event.event_date else "",
        event_location=event.location or "",
        mode="name",
        total=stats["total"],
        checked_in=stats["checked_in"],
        custom_html=custom_html,
        custom_css=custom_css,
        event_id=str(event_id),
    )
    return HTMLResponse(html)


# ── Search / Check-in API ──────────────────────────────────────

@router.post("/checkin/search", response_model=CheckinResult)
async def search_attendee(
    event_id: uuid.UUID,
    body: SearchRequest,
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Search attendee by name for check-in (public, no auth)."""
    name = body.name.strip()
    if not name:
        return CheckinResult(status="error", message="请输入姓名")

    try:
        result = await checkin_svc.checkin_by_name(event_id, name)
    except AttendeeNotFoundError:
        return CheckinResult(
            status="not_found",
            message=f"未找到「{name}」，请确认姓名后重试",
        )
    except InvalidStateTransitionError as e:
        return CheckinResult(status="error", message=str(e))

    # Ambiguous — multiple matches
    if isinstance(result, list):
        candidates = [
            CandidateItem(
                attendee_id=r["attendee_id"],
                name=r["name"],
                title=r.get("title"),
                organization=r.get("organization"),
            )
            for r in result
        ]
        return CheckinResult(
            status="ambiguous",
            message=f"找到 {len(candidates)} 位同名人员，请选择",
            candidates=candidates,
        )

    # Single match — already checked in or newly checked in
    msg = (
        f"{result['name']}，您已签到" if result.get("already_checked_in")
        else f"{result['name']}，签到成功！"
    )
    return CheckinResult(
        status="already" if result.get("already_checked_in") else "success",
        message=msg,
        attendee_name=result["name"],
        seat_label=result.get("seat_label"),
    )


@router.post("/checkin/confirm/{attendee_id}", response_model=CheckinResult)
async def confirm_checkin(
    event_id: uuid.UUID,
    attendee_id: uuid.UUID,
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Confirm check-in for a specific attendee (after disambiguation)."""
    try:
        result = await checkin_svc.checkin(attendee_id)
    except AttendeeNotFoundError:
        return CheckinResult(status="not_found", message="参会人员不存在")
    except InvalidStateTransitionError as e:
        return CheckinResult(status="error", message=str(e))

    msg = (
        f"{result['name']}，您已签到" if result.get("already_checked_in")
        else f"{result['name']}，签到成功！"
    )
    return CheckinResult(
        status="already" if result.get("already_checked_in") else "success",
        message=msg,
        attendee_name=result["name"],
        seat_label=result.get("seat_label"),
    )


@router.get("/checkin/stats")
async def checkin_stats(
    event_id: uuid.UUID,
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Live check-in stats (polled by the H5 page)."""
    return await checkin_svc.get_checkin_stats(event_id)
