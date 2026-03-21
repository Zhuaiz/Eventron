"""Export API routes — Excel download for attendees, seat maps, and badge PDFs."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.deps import (
    get_attendee_service,
    get_badge_template_service,
    get_event_service,
    get_seating_service,
)
from app.services.attendee_service import AttendeeService
from app.services.badge_template_service import BadgeTemplateService
from app.services.event_service import EventService
from app.services.exceptions import EventNotFoundError
from app.services.seating_service import SeatingService
from tools.badge_render import render_badges_pdf
from tools.excel_io import export_attendees_to_excel, export_seatmap_to_excel

router = APIRouter()


def _make_content_disposition(filename: str) -> str:
    """Build Content-Disposition with RFC 5987 UTF-8 encoding.

    Handles non-ASCII filenames (Chinese, etc.) correctly across
    all browsers.
    """
    ascii_name = filename.encode("ascii", errors="replace").decode()
    encoded = quote(filename, safe="")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded}"
    )


@router.get("/events/{event_id}/export/attendees")
async def export_attendees(
    event_id: uuid.UUID,
    att_svc: AttendeeService = Depends(get_attendee_service),
    seat_svc: SeatingService = Depends(get_seating_service),
    event_svc: EventService = Depends(get_event_service),
):
    """Export attendees as Excel, or a blank import template if none exist."""
    try:
        event = await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")

    attendees = await att_svc.list_attendees_for_event(event_id)
    seats = await seat_svc.get_seats(event_id)

    att_dicts = [
        {
            "id": str(a.id),
            "name": a.name,
            "title": a.title,
            "organization": a.organization,
            "department": a.department,
            "role": a.role,
            "phone": a.phone,
            "email": a.email,
            "status": a.status,
        }
        for a in attendees
    ]
    seat_dicts = [
        {
            "attendee_id": str(s.attendee_id) if s.attendee_id else None,
            "label": s.label,
            "row_num": s.row_num,
            "col_num": s.col_num,
        }
        for s in seats
    ]

    # No attendees → generate import template with example row
    if not att_dicts:
        att_dicts = [
            {
                "name": "(示例) 张三",
                "title": "产品经理",
                "organization": "示例公司",
                "department": "产品部",
                "role": "attendee",
                "phone": "13800138000",
                "email": "zhangsan@example.com",
                "status": "pending",
            }
        ]
        filename = f"{event.name}_导入模板.xlsx"
    else:
        filename = f"{event.name}_参会人员.xlsx"

    xlsx_bytes = export_attendees_to_excel(att_dicts, seat_dicts)

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _make_content_disposition(filename)},
    )


@router.get("/events/{event_id}/export/seatmap")
async def export_seatmap(
    event_id: uuid.UUID,
    seat_svc: SeatingService = Depends(get_seating_service),
    event_svc: EventService = Depends(get_event_service),
    att_svc: AttendeeService = Depends(get_attendee_service),
):
    """Export seat map as Excel file."""
    try:
        event = await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")

    seats = await seat_svc.get_seats(event_id)

    if not seats:
        raise HTTPException(
            status_code=404,
            detail="该活动还没有座位，请先生成座位网格",
        )

    attendees = await att_svc.list_attendees_for_event(event_id)
    att_lookup = {str(a.id): a.name for a in attendees}

    seat_dicts = [
        {
            "row_num": s.row_num,
            "col_num": s.col_num,
            "seat_type": s.seat_type,
            "attendee_name": att_lookup.get(str(s.attendee_id), ""),
        }
        for s in seats
    ]

    xlsx_bytes = export_seatmap_to_excel(
        seat_dicts, event.venue_rows, event.venue_cols
    )
    filename = f"{event.name}_座位图.xlsx"

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _make_content_disposition(filename)},
    )


@router.get("/events/{event_id}/export/badges")
async def export_badges(
    event_id: uuid.UUID,
    template_id: str | None = Query(None, description="BadgeTemplate UUID"),
    template_name: str = Query("business", description="Built-in: business|tent_card"),
    roles: str | None = Query(None, description="Comma-separated role filter"),
    event_svc: EventService = Depends(get_event_service),
    att_svc: AttendeeService = Depends(get_attendee_service),
    badge_svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Generate badge/tent-card PDF for all (or filtered) attendees.

    Use a built-in template (template_name) or a custom DB
    template (template_id).  Optional role filter (comma-separated).
    """
    try:
        event = await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")

    attendees = await att_svc.list_attendees_for_event(event_id)
    if not attendees:
        raise HTTPException(
            status_code=404,
            detail="该活动还没有参会人员，请先添加人员",
        )

    # Optional role filter
    role_filter = None
    if roles:
        role_filter = {r.strip() for r in roles.split(",") if r.strip()}

    att_dicts = [
        {
            "name": a.name,
            "title": a.title or "",
            "organization": a.organization or "",
            "role": a.role or "参会者",
            "priority": getattr(a, "priority", 0),
        }
        for a in attendees
        if not role_filter or (a.role or "参会者") in role_filter
    ]

    if not att_dicts:
        raise HTTPException(
            status_code=404,
            detail="筛选后没有匹配的参会人员",
        )

    event_date = ""
    if event.event_date:
        event_date = event.event_date.strftime("%Y年%m月%d日")

    custom_html = None
    custom_css = None
    if template_id:
        tpl = await badge_svc.get_template(uuid.UUID(template_id))
        if tpl:
            custom_html = tpl.html_template
            custom_css = tpl.css
            template_name = tpl.template_type or "business"

    pdf_bytes = render_badges_pdf(
        attendees=att_dicts,
        event_name=event.name,
        event_date=event_date,
        template_name=template_name,
        custom_html=custom_html,
        custom_css=custom_css,
    )

    label = "桌签" if template_name == "tent_card" else "胸牌"
    filename = f"{event.name}_{label}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": _make_content_disposition(filename)},
    )


@router.get("/events/{event_id}/export/badges/html")
async def export_badges_html(
    event_id: uuid.UUID,
    template_id: str | None = Query(None, description="BadgeTemplate UUID"),
    template_name: str = Query("business", description="Built-in: business|tent_card"),
    roles: str | None = Query(None, description="Comma-separated role filter"),
    event_svc: EventService = Depends(get_event_service),
    att_svc: AttendeeService = Depends(get_attendee_service),
    badge_svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Generate badge HTML page for browser printing (no WeasyPrint needed).

    Returns a self-contained HTML page with print-optimized CSS.
    Users can print via Ctrl+P with zero Chinese font issues.
    """
    from tools.badge_render import render_badges_html

    try:
        event = await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")

    attendees = await att_svc.list_attendees_for_event(event_id)
    if not attendees:
        raise HTTPException(
            status_code=404,
            detail="该活动还没有参会人员，请先添加人员",
        )

    role_filter = None
    if roles:
        role_filter = {r.strip() for r in roles.split(",") if r.strip()}

    att_dicts = [
        {
            "name": a.name,
            "title": a.title or "",
            "organization": a.organization or "",
            "role": a.role or "参会者",
            "priority": getattr(a, "priority", 0),
        }
        for a in attendees
        if not role_filter or (a.role or "参会者") in role_filter
    ]

    if not att_dicts:
        raise HTTPException(
            status_code=404,
            detail="筛选后没有匹配的参会人员",
        )

    event_date = ""
    if event.event_date:
        event_date = event.event_date.strftime("%Y年%m月%d日")

    custom_html = None
    custom_css = None
    if template_id:
        tpl = await badge_svc.get_template(uuid.UUID(template_id))
        if tpl:
            custom_html = tpl.html_template
            custom_css = tpl.css
            template_name = tpl.template_type or "business"

    html_str = render_badges_html(
        attendees=att_dicts,
        event_name=event.name,
        event_date=event_date,
        template_name=template_name,
        custom_html=custom_html,
        custom_css=custom_css,
    )

    return Response(
        content=html_str,
        media_type="text/html; charset=utf-8",
    )


@router.get("/events/{event_id}/export/badges/preview")
async def preview_badge_template(
    event_id: uuid.UUID,
    template_id: str | None = Query(None),
    template_name: str = Query("business"),
    event_svc: EventService = Depends(get_event_service),
    badge_svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Preview a badge template with sample data (single badge)."""
    from tools.badge_render import render_badges_html

    try:
        event = await event_svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")

    sample = [{
        "name": "张三",
        "title": "产品总监",
        "organization": "示例科技有限公司",
        "role": "嘉宾",
        "priority": 5,
    }]

    event_date = ""
    if event.event_date:
        event_date = event.event_date.strftime("%Y年%m月%d日")

    custom_html = None
    custom_css = None
    if template_id:
        tpl = await badge_svc.get_template(uuid.UUID(template_id))
        if tpl:
            custom_html = tpl.html_template
            custom_css = tpl.css
            template_name = tpl.template_type or "business"

    html_str = render_badges_html(
        attendees=sample,
        event_name=event.name,
        event_date=event_date,
        template_name=template_name,
        custom_html=custom_html,
        custom_css=custom_css,
    )

    return Response(
        content=html_str,
        media_type="text/html; charset=utf-8",
    )
