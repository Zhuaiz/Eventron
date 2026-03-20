"""Unit tests for Pydantic schemas — validate request/response shapes."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.attendee import AttendeeCreate
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.schemas.seat import AutoAssignRequest, SeatCreate


class TestEventSchemas:
    """Validation rules for event schemas."""

    def test_create_minimal(self):
        """Only name is required."""
        ev = EventCreate(name="Test Event")
        assert ev.name == "Test Event"
        assert ev.layout_type == "theater"
        assert ev.venue_rows == 0

    def test_create_full(self):
        """All fields set."""
        ev = EventCreate(
            name="Gala",
            description="Annual gala",
            venue_rows=10,
            venue_cols=5,
            layout_type="banquet",
            config={"allow_self_checkin": True},
        )
        assert ev.venue_rows == 10
        assert ev.config["allow_self_checkin"] is True

    def test_invalid_layout_type_rejected(self):
        """Unknown layout type should fail validation."""
        with pytest.raises(ValidationError):
            EventCreate(name="Bad", layout_type="stadium")

    def test_negative_rows_rejected(self):
        """Negative venue dimensions should fail."""
        with pytest.raises(ValidationError):
            EventCreate(name="Bad", venue_rows=-1)

    def test_update_partial(self):
        """Update schema allows partial fields."""
        upd = EventUpdate(name="New Name")
        assert upd.name == "New Name"
        assert upd.venue_rows is None

    def test_update_invalid_status(self):
        """Invalid status should fail."""
        with pytest.raises(ValidationError):
            EventUpdate(status="bogus")


class TestAttendeeSchemas:
    """Validation rules for attendee schemas."""

    def test_create_minimal(self):
        att = AttendeeCreate(name="张三")
        assert att.role == "参会者"
        assert att.priority == 0
        assert att.attrs == {}

    def test_create_with_priority(self):
        att = AttendeeCreate(name="李四", role="甲方嘉宾", priority=20, title="CEO")
        assert att.role == "甲方嘉宾"
        assert att.priority == 20
        assert att.title == "CEO"

    def test_custom_role_accepted(self):
        """Any free-text role label should be accepted."""
        att = AttendeeCreate(name="王五", role="参展商")
        assert att.role == "参展商"

    def test_priority_range(self):
        """Priority must be 0-100."""
        with pytest.raises(ValidationError):
            AttendeeCreate(name="Bad", priority=-1)
        with pytest.raises(ValidationError):
            AttendeeCreate(name="Bad", priority=101)

    def test_attrs_accepts_any_dict(self):
        att = AttendeeCreate(
            name="王五",
            attrs={"dietary": "vegetarian", "language": "zh"},
        )
        assert att.attrs["dietary"] == "vegetarian"


class TestSeatSchemas:
    """Validation rules for seat schemas."""

    def test_create_basic(self):
        s = SeatCreate(row_num=1, col_num=3)
        assert s.seat_type == "normal"
        assert s.zone is None

    def test_create_with_zone(self):
        s = SeatCreate(row_num=1, col_num=1, seat_type="reserved", zone="VIP区")
        assert s.zone == "VIP区"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            SeatCreate(row_num=1, col_num=1, seat_type="throne")

    def test_zero_row_rejected(self):
        with pytest.raises(ValidationError):
            SeatCreate(row_num=0, col_num=1)

    def test_auto_assign_defaults(self):
        req = AutoAssignRequest()
        assert req.strategy == "random"

    def test_auto_assign_priority(self):
        req = AutoAssignRequest(strategy="priority_first")
        assert req.strategy == "priority_first"

    def test_auto_assign_by_zone(self):
        req = AutoAssignRequest(strategy="by_zone")
        assert req.strategy == "by_zone"

    def test_auto_assign_invalid_strategy(self):
        with pytest.raises(ValidationError):
            AutoAssignRequest(strategy="magic")
