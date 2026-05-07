"""Public check-in routes — NO JWT required.

These endpoints are accessed by attendees on their phones after scanning
the event QR code.  They live under ``/p/{event_id}/checkin``.

Includes a simple in-memory rate limiter to prevent abuse.
"""

import time
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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


# ── Simple in-memory rate limiter ─────────────────────────────
# Keyed by (client_ip, event_id), sliding window of 60s, max 30 requests.

_rate_buckets: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60.0   # seconds
_RATE_LIMIT = 30       # max requests per window per IP+event


def _check_rate_limit(request: Request, event_id: uuid.UUID) -> None:
    """Raise 429 if the client exceeds the rate limit."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{event_id}"
    now = time.monotonic()

    # Prune expired entries
    bucket = _rate_buckets[key]
    cutoff = now - _RATE_WINDOW
    _rate_buckets[key] = [t for t in bucket if t > cutoff]

    if len(_rate_buckets[key]) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="请求过于频繁，请稍后再试",
        )
    _rate_buckets[key].append(now)

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
    preview: str = Query(default=None, description="Set to 'staging' to preview staged page"),
    event_svc: EventService = Depends(get_event_service),
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Serve the mobile H5 check-in page for an event.

    Pass ``?preview=staging`` to preview the staged (not yet live) page.
    """
    from tools.page_render import render_checkin_page

    try:
        event = await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="活动不存在")

    stats = await checkin_svc.get_checkin_stats(event_id)

    from pathlib import Path
    base_dir = Path(f"uploads/events/{event_id}")

    # Staging preview — show staged page if requested and available
    if preview == "staging":
        staging_page = base_dir / "checkin_page_staging.html"
        if staging_page.exists():
            return HTMLResponse(
                staging_page.read_text(encoding="utf-8"),
            )

    # Live page — check if there's a custom checkin page deployed
    custom_page = base_dir / "checkin_page.html"
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
        custom_html=None,
        custom_css=None,
        event_id=str(event_id),
    )
    return HTMLResponse(html)


# ── Suggest (autocomplete, no side-effects) ───────────────────

@router.post("/checkin/suggest")
async def suggest_attendee(
    event_id: uuid.UUID,
    body: SearchRequest,
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Suggest attendees by name/pinyin — no check-in side-effect.

    Used for live autocomplete as the user types.
    """
    name = body.name.strip()
    if not name:
        return {"candidates": []}

    candidates = await checkin_svc.suggest_by_name(event_id, name)
    return {"candidates": candidates}


# ── Search / Check-in API ──────────────────────────────────────

@router.post("/checkin/search", response_model=CheckinResult)
async def search_attendee(
    event_id: uuid.UUID,
    body: SearchRequest,
    request: Request,
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Search attendee by name for check-in (public, no auth)."""
    _check_rate_limit(request, event_id)
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
    request: Request,
    checkin_svc: CheckinService = Depends(get_checkin_service),
):
    """Confirm check-in for a specific attendee (after disambiguation)."""
    _check_rate_limit(request, event_id)
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


@router.get("/checkin/page-status")
async def checkin_page_status(event_id: uuid.UUID):
    """Filesystem probe: which custom-page artifacts exist for this event.

    The organizer-side design tab uses this to decide whether the preview
    iframe should target the live URL or ``?preview=staging``. Public so the
    same iframe (cookie-less) can hit it without JWT plumbing; nothing
    sensitive — just three booleans.
    """
    from pathlib import Path

    base_dir = Path(f"uploads/events/{event_id}")
    return {
        "has_live": (base_dir / "checkin_page.html").exists(),
        "has_staging": (base_dir / "checkin_page_staging.html").exists(),
        "has_backup": (base_dir / "checkin_page_backup.html").exists(),
    }
