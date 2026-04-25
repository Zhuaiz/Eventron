"""Attendee management — business logic for attendee operations."""

import uuid

from app.models.attendee import Attendee
from app.repositories.attendee_repo import AttendeeRepository
from app.services.exceptions import AttendeeNotFoundError


class AttendeeService:
    """Business logic for attendee CRUD and domain operations."""

    def __init__(self, attendee_repo: AttendeeRepository):
        self._repo = attendee_repo

    async def create_attendee(
        self, event_id: uuid.UUID, **kwargs
    ) -> Attendee:
        """Create a new attendee in pending status."""
        kwargs.setdefault("status", "pending")
        kwargs["event_id"] = event_id
        return await self._repo.create(**kwargs)

    async def get_attendee(self, attendee_id: uuid.UUID) -> Attendee:
        """Fetch an attendee by ID, raise if not found."""
        attendee = await self._repo.get_by_id(attendee_id)
        if attendee is None:
            raise AttendeeNotFoundError(f"Attendee {attendee_id} not found")
        return attendee

    async def list_attendees_for_event(
        self,
        event_id: uuid.UUID,
        role: str | None = None,
        status: str | None = None,
    ) -> list[Attendee]:
        """List attendees for an event, optionally filtered by role or status."""
        attendees = await self._repo.get_by_event(event_id)

        if role:
            attendees = [a for a in attendees if a.role == role]
        if status:
            attendees = [a for a in attendees if a.status == status]

        return attendees

    async def update_attendee(
        self, attendee_id: uuid.UUID, **kwargs
    ) -> Attendee:
        """Update attendee fields."""
        attendee = await self.get_attendee(attendee_id)
        result = await self._repo.update(attendee_id, **kwargs)
        if result is None:
            raise AttendeeNotFoundError(f"Attendee {attendee_id} not found")
        return result

    async def delete_attendee(self, attendee_id: uuid.UUID) -> bool:
        """Delete an attendee."""
        attendee = await self.get_attendee(attendee_id)
        return await self._repo.delete(attendee_id)

    async def delete_all_for_event(self, event_id: uuid.UUID) -> int:
        """Delete every attendee for an event. Returns count removed.

        Used by the agent's `delete_all_attendees` and
        `regenerate_roster_from_excel` tools when the user wants a clean
        slate before re-importing. Seats are unassigned (kept) — only the
        attendee rows go away.
        """
        return await self._repo.delete_all_for_event(event_id)
