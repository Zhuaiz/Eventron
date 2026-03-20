"""Unit tests for DashboardService — aggregated event stats."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.dashboard_service import DashboardService
from app.services.exceptions import EventNotFoundError


class FakeAttendee:
    def __init__(self, role="参会者", status="confirmed", priority=0):
        self.role = role
        self.status = status
        self.priority = priority


class FakeSeat:
    def __init__(self, attendee_id=None):
        self.attendee_id = attendee_id


def _make_attendee(role="参会者", status="confirmed", priority=0):
    return FakeAttendee(role=role, status=status, priority=priority)


def _make_seat(attendee_id=None):
    return FakeSeat(attendee_id=attendee_id)


class TestDashboardService:
    """DashboardService with mocked repositories."""

    @pytest.fixture
    def repos(self):
        return {
            "event_repo": AsyncMock(),
            "attendee_repo": AsyncMock(),
            "seat_repo": AsyncMock(),
            "approval_repo": AsyncMock(),
        }

    @pytest.fixture
    def svc(self, repos):
        return DashboardService(**repos)

    async def test_event_not_found(self, svc, repos):
        repos["event_repo"].get_by_id.return_value = None
        with pytest.raises(EventNotFoundError):
            await svc.get_event_stats(uuid.uuid4())

    async def test_basic_stats(self, svc, repos):
        eid = uuid.uuid4()
        mock_event = AsyncMock()
        mock_event.name = "Test Event"
        mock_event.status = "active"
        repos["event_repo"].get_by_id.return_value = mock_event
        repos["attendee_repo"].get_by_event.return_value = [
            _make_attendee("参会者", "confirmed", priority=0),
            _make_attendee("甲方嘉宾", "checked_in", priority=15),
            _make_attendee("演讲嘉宾", "checked_in", priority=10),
            _make_attendee("参会者", "pending", priority=0),
        ]
        repos["seat_repo"].get_by_event.return_value = [
            _make_seat(uuid.uuid4()),
            _make_seat(uuid.uuid4()),
            _make_seat(None),
            _make_seat(None),
            _make_seat(None),
        ]
        repos["approval_repo"].get_pending_by_event.return_value = [
            AsyncMock(), AsyncMock()
        ]

        stats = await svc.get_event_stats(eid)

        assert stats["event_name"] == "Test Event"
        assert stats["total_attendees"] == 4
        assert stats["checked_in_count"] == 2
        assert stats["pending_count"] == 1
        assert stats["confirmed_count"] == 1
        assert stats["absent_count"] == 0
        assert stats["cancelled_count"] == 0
        assert stats["checkin_rate"] == 0.5
        assert stats["seats_total"] == 5
        assert stats["seats_occupied"] == 2
        assert stats["seats_available"] == 3
        assert stats["seat_utilization_rate"] == 0.4
        assert stats["pending_approvals"] == 2
        assert stats["high_priority_count"] == 2  # priority >= 10: 甲方嘉宾(15) + 演讲嘉宾(10)
        assert stats["mid_priority_count"] == 0   # 1 <= priority < 10: none
        assert stats["vip_checked_in"] == 2        # priority >= 1 + checked_in

    async def test_empty_event(self, svc, repos):
        mock_event = AsyncMock()
        mock_event.name = "Empty"
        mock_event.status = "draft"
        repos["event_repo"].get_by_id.return_value = mock_event
        repos["attendee_repo"].get_by_event.return_value = []
        repos["seat_repo"].get_by_event.return_value = []
        repos["approval_repo"].get_pending_by_event.return_value = []

        stats = await svc.get_event_stats(uuid.uuid4())

        assert stats["total_attendees"] == 0
        assert stats["checkin_rate"] == 0
        assert stats["seat_utilization_rate"] == 0
        assert stats["seats_total"] == 0
        assert stats["seats_available"] == 0
