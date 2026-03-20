"""Unit tests for IdentityService — user identity resolution."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.identity_service import (
    IdentityService,
    extract_name,
    looks_like_identity,
)


# ── Pure function tests ──────────────────────────────────────

class TestLooksLikeIdentity:
    """Test identity message detection."""

    def test_chinese_prefix(self):
        assert looks_like_identity("我是张三")
        assert looks_like_identity("我叫李四")

    def test_english_prefix(self):
        assert looks_like_identity("I am John")
        assert looks_like_identity("I'm Alice")
        assert looks_like_identity("This is Bob")

    def test_short_chinese_name(self):
        assert looks_like_identity("张三")
        assert looks_like_identity("王大明")

    def test_not_identity(self):
        assert not looks_like_identity("签到")
        assert not looks_like_identity("查看座位")
        assert not looks_like_identity("Hello there")

    def test_single_char_not_identity(self):
        assert not looks_like_identity("张")


class TestExtractName:
    """Test name extraction from messages."""

    def test_chinese_prefix(self):
        assert extract_name("我是张三") == "张三"
        assert extract_name("我叫李四") == "李四"

    def test_english_prefix(self):
        assert extract_name("I am John") == "John"
        assert extract_name("I'm Alice") == "Alice"

    def test_bare_chinese_name(self):
        assert extract_name("张三") == "张三"

    def test_no_name_found(self):
        assert extract_name("签到") is None
        assert extract_name("Hello") is None


# ── IdentityService tests ────────────────────────────────────

class TestIdentityService:
    """IdentityService with mocked repository."""

    @pytest.fixture
    def mock_repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, mock_repo):
        return IdentityService(mock_repo)

    async def test_auto_identify_found(self, svc, mock_repo):
        class FakeEvent:
            name = "Annual Meeting"

        class FakeAttendee:
            id = uuid.uuid4()
            name = "张三"
            title = "总经理"
            organization = "Acme"
            role = "甲方嘉宾"
            event_id = uuid.uuid4()
            event = FakeEvent()

        mock_repo.find_by_wecom_id_in_active_event.return_value = FakeAttendee()

        profile = await svc.auto_identify("wecom_123")
        assert profile is not None
        assert profile["name"] == "张三"
        assert profile["event_name"] == "Annual Meeting"

    async def test_auto_identify_not_found(self, svc, mock_repo):
        mock_repo.find_by_wecom_id_in_active_event.return_value = None
        profile = await svc.auto_identify("unknown")
        assert profile is None

    async def test_identify_by_name_success(self, svc, mock_repo):
        class FakeEvent:
            name = "Summit"

        class FakeAttendee:
            id = uuid.uuid4()
            name = "李四"
            title = "副总"
            organization = "Beta"
            role = "参会者"
            event_id = uuid.uuid4()
            event = FakeEvent()

        fake = FakeAttendee()
        mock_repo.fuzzy_match_in_active_events.return_value = fake
        mock_repo.bind_wecom_id.return_value = fake

        profile = await svc.identify_by_name("李四", "wecom_456")
        assert profile["name"] == "李四"
        mock_repo.bind_wecom_id.assert_called_once()

    async def test_identify_by_name_no_match(self, svc, mock_repo):
        mock_repo.fuzzy_match_in_active_events.return_value = None
        profile = await svc.identify_by_name("Nobody", "wecom_789")
        assert profile is None
