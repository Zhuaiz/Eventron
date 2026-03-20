"""Seat assignment + swap logic — core business rules."""

import uuid

from app.models.seat import Seat
from app.repositories.attendee_repo import AttendeeRepository
from app.repositories.seat_repo import SeatRepository
from app.services.exceptions import (
    AttendeeNotFoundError,
    DuplicateAssignmentError,
    SeatNotAvailableError,
    SeatNotFoundError,
)
from tools.seating_engine import (
    assign_seats_by_department,
    assign_seats_by_zone,
    assign_seats_priority_first,
    assign_seats_random,
    assign_seats_vip_first,
)


class SeatingService:
    """Business logic for seat assignment and management."""

    def __init__(
        self,
        seat_repo: SeatRepository,
        attendee_repo: AttendeeRepository,
    ):
        self._seat_repo = seat_repo
        self._attendee_repo = attendee_repo

    async def create_venue_grid(
        self, event_id: uuid.UUID, rows: int, cols: int
    ) -> list[Seat]:
        """Create a full seat grid for an event."""
        return await self._seat_repo.bulk_create_grid(event_id, rows, cols)

    async def get_seats(self, event_id: uuid.UUID) -> list[Seat]:
        """Get all seats for an event."""
        return await self._seat_repo.get_by_event(event_id)

    async def get_available_seats(self, event_id: uuid.UUID) -> list[Seat]:
        """Get unoccupied, non-disabled seats."""
        return await self._seat_repo.get_available_seats(event_id)

    async def auto_assign(
        self,
        event_id: uuid.UUID,
        strategy: str = "random",
        zone_rules: list[dict] | None = None,
    ) -> list[dict[str, str]]:
        """Run auto-assignment algorithm and persist results.

        Args:
            event_id: Target event.
            strategy: 'random', 'priority_first', 'by_department',
                      'by_zone', or legacy 'vip_first'.
            zone_rules: For by_zone strategy, list of
                {zone: str, min_priority: int}.

        Returns:
            List of {attendee_id, seat_id} assignments made.
        """
        attendees = await self._attendee_repo.get_by_event(event_id)
        all_seats = await self._seat_repo.get_by_event(event_id)
        seats = await self._seat_repo.get_available_seats(event_id)

        seated_ids = {
            str(s.attendee_id) for s in all_seats if s.attendee_id is not None
        }

        att_dicts = [
            {
                "id": str(a.id),
                "name": a.name,
                "role": a.role,
                "priority": getattr(a, "priority", 0),
                "department": a.department,
            }
            for a in attendees
            if a.status in ("confirmed", "pending")
            and str(a.id) not in seated_ids
        ]
        seat_dicts = [
            {
                "id": str(s.id),
                "row_num": s.row_num,
                "col_num": s.col_num,
                "zone": getattr(s, "zone", None),
            }
            for s in seats
        ]

        if strategy == "priority_first":
            assignments = assign_seats_priority_first(att_dicts, seat_dicts)
        elif strategy == "by_department":
            assignments = assign_seats_by_department(att_dicts, seat_dicts)
        elif strategy == "by_zone":
            assignments = assign_seats_by_zone(
                att_dicts, seat_dicts, zone_rules
            )
        elif strategy == "vip_first":
            # Legacy compat
            assignments = assign_seats_vip_first(att_dicts, seat_dicts)
        else:
            assignments = assign_seats_random(att_dicts, seat_dicts)

        for a in assignments:
            await self._seat_repo.assign_attendee(
                uuid.UUID(a["seat_id"]),
                uuid.UUID(a["attendee_id"]),
            )

        return assignments

    async def assign_seat(
        self, seat_id: uuid.UUID, attendee_id: uuid.UUID
    ) -> Seat:
        """Manually assign one attendee to one seat."""
        seat = await self._seat_repo.get_by_id(seat_id)
        if seat is None:
            raise SeatNotFoundError(f"Seat {seat_id} not found")
        if seat.attendee_id is not None:
            raise SeatNotAvailableError(f"Seat {seat_id} is already occupied")
        if seat.seat_type in ("disabled", "aisle"):
            raise SeatNotAvailableError(f"Seat {seat_id} is {seat.seat_type}")

        attendee = await self._attendee_repo.get_by_id(attendee_id)
        if attendee is None:
            raise AttendeeNotFoundError(f"Attendee {attendee_id} not found")

        existing = await self._seat_repo.get_by_attendee(attendee_id)
        if existing is not None:
            raise DuplicateAssignmentError(
                f"Attendee {attendee_id} already has seat {existing.label}"
            )

        result = await self._seat_repo.assign_attendee(seat_id, attendee_id)
        if result is None:
            raise SeatNotFoundError(f"Seat {seat_id} not found")
        return result

    async def unassign_seat(self, seat_id: uuid.UUID) -> Seat:
        """Remove attendee from a seat."""
        result = await self._seat_repo.unassign(seat_id)
        if result is None:
            raise SeatNotFoundError(f"Seat {seat_id} not found")
        return result

    async def swap_seats(
        self, seat_a_id: uuid.UUID, seat_b_id: uuid.UUID
    ) -> tuple[Seat, Seat]:
        """Swap attendees between two seats."""
        a, b = await self._seat_repo.swap_seats(seat_a_id, seat_b_id)
        if a is None or b is None:
            raise SeatNotFoundError("One or both seats not found")
        return (a, b)
