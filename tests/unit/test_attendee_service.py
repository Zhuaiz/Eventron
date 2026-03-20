"""Unit tests for AttendeeService — attendee CRUD operations."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.attendee_service import AttendeeService
from app.services.exceptions import AttendeeNotFoundError


def _fake_attendee(**overrides):
    """Build a fake attendee object with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "event_id": uuid.uuid4(),
        "name": "张三",
        "title": "总经理",
        "organization": "Acme",
        "department": "管理层",
        "role": "参会者",
        "priority": 0,
        "phone": "13800000001",
        "email": "zhang@acme.com",
        "attrs": {},
        "status": "pending",
        "wecom_user_id": None,
        "lark_user_id": None,
    }
    defaults.update(overrides)

    class FakeAttendee:
        pass

    obj = FakeAttendee()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


class TestAttendeeServiceCreate:
    """Attendee creation tests."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return AttendeeService(repo)

    async def test_create_defaults_to_pending(self, svc, repo):
        fake = _fake_attendee()
        repo.create.return_value = fake
        eid = uuid.uuid4()
        result = await svc.create_attendee(eid, name="张三")
        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["status"] == "pending"
        assert call_kwargs["event_id"] == eid

    async def test_create_with_all_fields(self, svc, repo):
        fake = _fake_attendee(role="甲方嘉宾")
        repo.create.return_value = fake
        eid = uuid.uuid4()
        result = await svc.create_attendee(
            eid, name="李四", title="副总", role="甲方嘉宾", organization="Beta"
        )
        assert result.role == "甲方嘉宾"

    async def test_create_preserves_explicit_status(self, svc, repo):
        fake = _fake_attendee(status="confirmed")
        repo.create.return_value = fake
        await svc.create_attendee(uuid.uuid4(), name="王五", status="confirmed")
        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["status"] == "confirmed"


class TestAttendeeServiceGet:
    """Attendee retrieval tests."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return AttendeeService(repo)

    async def test_get_found(self, svc, repo):
        fake = _fake_attendee()
        repo.get_by_id.return_value = fake
        result = await svc.get_attendee(fake.id)
        assert result.name == "张三"

    async def test_get_not_found_raises(self, svc, repo):
        repo.get_by_id.return_value = None
        with pytest.raises(AttendeeNotFoundError):
            await svc.get_attendee(uuid.uuid4())


class TestAttendeeServiceList:
    """Attendee listing with filters."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return AttendeeService(repo)

    async def test_list_all(self, svc, repo):
        eid = uuid.uuid4()
        repo.get_by_event.return_value = [
            _fake_attendee(role="参会者"),
            _fake_attendee(role="甲方嘉宾"),
        ]
        result = await svc.list_attendees_for_event(eid)
        assert len(result) == 2

    async def test_filter_by_role(self, svc, repo):
        repo.get_by_event.return_value = [
            _fake_attendee(role="参会者"),
            _fake_attendee(role="甲方嘉宾"),
            _fake_attendee(role="甲方嘉宾"),
        ]
        result = await svc.list_attendees_for_event(uuid.uuid4(), role="甲方嘉宾")
        assert len(result) == 2

    async def test_filter_by_status(self, svc, repo):
        repo.get_by_event.return_value = [
            _fake_attendee(status="pending"),
            _fake_attendee(status="checked_in"),
        ]
        result = await svc.list_attendees_for_event(uuid.uuid4(), status="checked_in")
        assert len(result) == 1

    async def test_filter_by_role_and_status(self, svc, repo):
        repo.get_by_event.return_value = [
            _fake_attendee(role="甲方嘉宾", status="checked_in"),
            _fake_attendee(role="甲方嘉宾", status="pending"),
            _fake_attendee(role="参会者", status="checked_in"),
        ]
        result = await svc.list_attendees_for_event(
            uuid.uuid4(), role="甲方嘉宾", status="checked_in"
        )
        assert len(result) == 1

    async def test_empty_event(self, svc, repo):
        repo.get_by_event.return_value = []
        result = await svc.list_attendees_for_event(uuid.uuid4())
        assert len(result) == 0


class TestAttendeeServiceUpdate:
    """Attendee update tests."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return AttendeeService(repo)

    async def test_update_success(self, svc, repo):
        aid = uuid.uuid4()
        repo.get_by_id.return_value = _fake_attendee(id=aid)
        updated = _fake_attendee(id=aid, title="CEO")
        repo.update.return_value = updated
        result = await svc.update_attendee(aid, title="CEO")
        assert result.title == "CEO"

    async def test_update_not_found_raises(self, svc, repo):
        repo.get_by_id.return_value = None
        with pytest.raises(AttendeeNotFoundError):
            await svc.update_attendee(uuid.uuid4(), title="CEO")

    async def test_update_returns_none_after_get_raises(self, svc, repo):
        aid = uuid.uuid4()
        repo.get_by_id.return_value = _fake_attendee(id=aid)
        repo.update.return_value = None
        with pytest.raises(AttendeeNotFoundError):
            await svc.update_attendee(aid, title="CEO")


class TestAttendeeServiceDelete:
    """Attendee deletion tests."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return AttendeeService(repo)

    async def test_delete_success(self, svc, repo):
        aid = uuid.uuid4()
        repo.get_by_id.return_value = _fake_attendee(id=aid)
        repo.delete.return_value = True
        result = await svc.delete_attendee(aid)
        assert result is True

    async def test_delete_not_found_raises(self, svc, repo):
        repo.get_by_id.return_value = None
        with pytest.raises(AttendeeNotFoundError):
            await svc.delete_attendee(uuid.uuid4())
