"""Dashboard aggregation service — read-only stats for organizer portal."""

from __future__ import annotations

import uuid

from app.repositories.approval_repo import ApprovalRepository
from app.repositories.attendee_repo import AttendeeRepository
from app.repositories.event_repo import EventRepository
from app.repositories.seat_repo import SeatRepository
from app.services.exceptions import EventNotFoundError


class DashboardService:
    """Aggregates cross-entity stats for the organizer dashboard."""

    def __init__(
        self,
        event_repo: EventRepository,
        attendee_repo: AttendeeRepository,
        seat_repo: SeatRepository,
        approval_repo: ApprovalRepository,
    ):
        self._event_repo = event_repo
        self._attendee_repo = attendee_repo
        self._seat_repo = seat_repo
        self._approval_repo = approval_repo

    async def get_event_stats(self, event_id: uuid.UUID) -> dict:
        """Build dashboard stats for a single event."""
        event = await self._event_repo.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id} not found")

        attendees = await self._attendee_repo.get_by_event(event_id)
        seats = await self._seat_repo.get_by_event(event_id)
        pending = await self._approval_repo.get_pending_by_event(event_id)

        total = len(attendees)
        checked_in = sum(1 for a in attendees if a.status == "checked_in")
        pending_count = sum(1 for a in attendees if a.status == "pending")
        confirmed_count = sum(1 for a in attendees if a.status == "confirmed")
        absent_count = sum(1 for a in attendees if a.status == "absent")
        cancelled_count = sum(1 for a in attendees if a.status == "cancelled")
        # Priority-based VIP stats (priority >= 10 = high-tier)
        high_priority = [a for a in attendees if getattr(a, "priority", 0) >= 10]
        mid_priority = [a for a in attendees if 1 <= getattr(a, "priority", 0) < 10]
        vip_checked = sum(
            1 for a in attendees
            if getattr(a, "priority", 0) >= 1 and a.status == "checked_in"
        )

        total_seats = len(seats)
        assigned = sum(1 for s in seats if s.attendee_id is not None)

        return {
            "event_name": event.name,
            "event_status": event.status,
            "total_attendees": total,
            "checked_in_count": checked_in,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            "absent_count": absent_count,
            "cancelled_count": cancelled_count,
            "checkin_rate": round(checked_in / total, 3) if total > 0 else 0,
            "seats_total": total_seats,
            "seats_occupied": assigned,
            "seats_available": total_seats - assigned,
            "seat_utilization_rate": (
                round(assigned / total_seats, 3) if total_seats > 0 else 0
            ),
            "pending_approvals": len(pending),
            "high_priority_count": len(high_priority),
            "mid_priority_count": len(mid_priority),
            "vip_checked_in": vip_checked,
        }
