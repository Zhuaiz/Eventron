"""Event lifecycle management — business logic for events."""

import uuid

from app.models.event import Event
from app.repositories.event_repo import EventRepository
from app.services.exceptions import EventNotFoundError, InvalidStateTransitionError


# Valid state transitions
_VALID_TRANSITIONS = {
    "draft": {"active", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": {"draft"},
}


class EventService:
    """Business logic for event lifecycle operations."""

    def __init__(self, event_repo: EventRepository):
        self._repo = event_repo

    async def create_event(self, **kwargs) -> Event:
        """Create a new event in draft status."""
        kwargs.setdefault("status", "draft")
        return await self._repo.create(**kwargs)

    async def get_event(self, event_id: uuid.UUID) -> Event:
        """Fetch an event by ID, raise if not found."""
        event = await self._repo.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        return event

    async def list_events(self, status: str | None = None) -> list[Event]:
        """List events, optionally filtered by status."""
        if status:
            return await self._repo.get_by_status(status)
        return await self._repo.list_all()

    async def update_event(self, event_id: uuid.UUID, **kwargs) -> Event:
        """Update event fields. Validates state transitions."""
        event = await self.get_event(event_id)

        new_status = kwargs.get("status")
        if new_status and new_status != event.status:
            allowed = _VALID_TRANSITIONS.get(event.status, set())
            if new_status not in allowed:
                raise InvalidStateTransitionError(
                    f"Cannot transition from '{event.status}' to '{new_status}'. "
                    f"Allowed: {allowed or 'none'}"
                )

        result = await self._repo.update(event_id, **kwargs)
        if result is None:
            raise EventNotFoundError(f"Event {event_id} not found")
        return result

    async def activate_event(self, event_id: uuid.UUID) -> Event:
        """Move event from draft to active."""
        return await self.update_event(event_id, status="active")

    async def complete_event(self, event_id: uuid.UUID) -> Event:
        """Mark event as completed."""
        return await self.update_event(event_id, status="completed")

    async def cancel_event(self, event_id: uuid.UUID) -> Event:
        """Cancel an event."""
        return await self.update_event(event_id, status="cancelled")

    async def delete_event(self, event_id: uuid.UUID) -> bool:
        """Delete an event. Only draft or cancelled events can be deleted."""
        event = await self.get_event(event_id)
        if event.status not in ("draft", "cancelled"):
            raise InvalidStateTransitionError(
                f"Only draft or cancelled events can be deleted"
                f" (current: {event.status})"
            )
        return await self._repo.delete(event_id)

    async def duplicate_event(self, event_id: uuid.UUID) -> Event:
        """Duplicate an event (layout + config, no attendees).

        Creates a new draft event with the same venue settings.
        """
        source = await self.get_event(event_id)
        return await self._repo.create(
            name=f"{source.name} (Copy)",
            description=source.description,
            location=source.location,
            venue_rows=source.venue_rows,
            venue_cols=source.venue_cols,
            layout_type=source.layout_type,
            config=dict(source.config) if source.config else {},
            status="draft",
        )
