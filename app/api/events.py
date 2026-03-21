"""Event CRUD API routes — thin layer, delegates to EventService."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_event_service
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.services.event_service import EventService
from app.services.exceptions import EventNotFoundError, InvalidStateTransitionError

router = APIRouter()


@router.post("/", response_model=EventResponse, status_code=201)
async def create_event(
    body: EventCreate,
    svc: EventService = Depends(get_event_service),
):
    """Create a new event."""
    event = await svc.create_event(**body.model_dump())
    return EventResponse.model_validate(event)


@router.get("/", response_model=list[EventResponse])
async def list_events(
    status: Optional[str] = None,
    svc: EventService = Depends(get_event_service),
):
    """List events, optionally filtered by status."""
    events = await svc.list_events(status=status)
    return [EventResponse.model_validate(e) for e in events]


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    svc: EventService = Depends(get_event_service),
):
    """Get a single event by ID."""
    try:
        event = await svc.get_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventResponse.model_validate(event)


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: uuid.UUID,
    body: EventUpdate,
    svc: EventService = Depends(get_event_service),
):
    """Partial update of an event."""
    try:
        event = await svc.update_event(
            event_id, **body.model_dump(exclude_unset=True)
        )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return EventResponse.model_validate(event)


@router.post("/{event_id}/activate", response_model=EventResponse)
async def activate_event(
    event_id: uuid.UUID,
    svc: EventService = Depends(get_event_service),
):
    """Activate a draft event."""
    try:
        event = await svc.activate_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return EventResponse.model_validate(event)


@router.post("/{event_id}/complete", response_model=EventResponse)
async def complete_event(
    event_id: uuid.UUID,
    svc: EventService = Depends(get_event_service),
):
    """Mark an active event as completed."""
    try:
        event = await svc.complete_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return EventResponse.model_validate(event)


@router.post("/{event_id}/cancel", response_model=EventResponse)
async def cancel_event(
    event_id: uuid.UUID,
    svc: EventService = Depends(get_event_service),
):
    """Cancel an event (from draft or active)."""
    try:
        event = await svc.cancel_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return EventResponse.model_validate(event)


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: uuid.UUID,
    svc: EventService = Depends(get_event_service),
):
    """Delete a draft event."""
    try:
        await svc.delete_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{event_id}/duplicate", response_model=EventResponse, status_code=201)
async def duplicate_event(
    event_id: uuid.UUID,
    svc: EventService = Depends(get_event_service),
):
    """Duplicate an event (copies layout + config, not attendees)."""
    try:
        event = await svc.duplicate_event(event_id)
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventResponse.model_validate(event)
