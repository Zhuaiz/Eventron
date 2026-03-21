"""Badge template API routes — CRUD for badge/tent card templates."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.deps import get_badge_template_service
from app.schemas.badge_template import (
    BadgeTemplateCreate,
    BadgeTemplateResponse,
    BadgeTemplateUpdate,
)
from app.services.badge_template_service import BadgeTemplateService
from app.services.exceptions import TemplateNotFoundError

router = APIRouter()


@router.post("/", response_model=BadgeTemplateResponse, status_code=201)
async def create_template(
    body: BadgeTemplateCreate,
    svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Create a new badge/tent card template."""
    tmpl = await svc.create_template(**body.model_dump())
    return BadgeTemplateResponse.model_validate(tmpl)


@router.get("/", response_model=list[BadgeTemplateResponse])
async def list_templates(
    template_type: Optional[str] = None,
    svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """List templates, optionally filtered by type."""
    templates = await svc.list_templates(template_type=template_type)
    return [BadgeTemplateResponse.model_validate(t) for t in templates]


@router.get("/builtins", response_model=list[BadgeTemplateResponse])
async def list_builtins(
    svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """List all built-in templates."""
    templates = await svc.list_builtins()
    return [BadgeTemplateResponse.model_validate(t) for t in templates]


@router.get("/preview")
async def preview_template(
    template_id: str | None = Query(None),
    template_name: str = Query("conference"),
    svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Preview a template with sample data — no event required.

    Use for the global template management page where there's no eventId.
    """
    from tools.badge_render import render_badges_html

    sample = [{
        "name": "张三",
        "title": "产品总监",
        "organization": "示例科技有限公司",
        "role": "嘉宾",
        "priority": 5,
    }]

    custom_html = None
    custom_css = None
    if template_id:
        tpl = await svc.get_template(uuid.UUID(template_id))
        if tpl:
            custom_html = tpl.html_template
            custom_css = tpl.css
            template_name = tpl.template_type or "conference"

    html_str = render_badges_html(
        attendees=sample,
        event_name="示例活动 · 年度峰会",
        event_date="2026年3月23日",
        template_name=template_name,
        custom_html=custom_html,
        custom_css=custom_css,
    )

    return Response(
        content=html_str,
        media_type="text/html; charset=utf-8",
    )


@router.get("/{template_id}", response_model=BadgeTemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Get a single template by ID."""
    try:
        tmpl = await svc.get_template(template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return BadgeTemplateResponse.model_validate(tmpl)


@router.patch("/{template_id}", response_model=BadgeTemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    body: BadgeTemplateUpdate,
    svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Update a custom template. Built-in templates cannot be modified."""
    try:
        tmpl = await svc.update_template(
            template_id, **body.model_dump(exclude_unset=True)
        )
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return BadgeTemplateResponse.model_validate(tmpl)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    svc: BadgeTemplateService = Depends(get_badge_template_service),
):
    """Delete a custom template. Built-in templates cannot be deleted."""
    try:
        await svc.delete_template(template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
