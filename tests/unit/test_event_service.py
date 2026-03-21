"""Unit tests for EventService — event lifecycle management."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.event_service import EventService
from app.services.exceptions import EventNotFoundError, InvalidStateTransitionError


def _mock_event(**overrides):
    """Create a mock Event ORM object."""
    ev = MagicMock()
    ev.id = overrides.get("id", uuid.uuid4())
    ev.name = overrides.get("name", "Test Event")
    ev.description = overrides.get("description", "Test Description")
    ev.location = overrides.get("location", "Test Location")
    ev.status = overrides.get("status", "draft")
    ev.venue_rows = overrides.get("venue_rows", 5)
    ev.venue_cols = overrides.get("venue_cols", 5)
    ev.layout_type = overrides.get("layout_type", "theater")
    ev.config = overrides.get("config", {})
    ev.created_by = overrides.get("created_by", None)
    return ev


class TestEventServiceCreate:
    """Test event creation."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    async def test_create_defaults_to_draft(self, svc, repo):
        """New events default to draft status."""
        mock_event = _mock_event(status="draft")
        repo.create.return_value = mock_event

        result = await svc.create_event(name="Annual Meeting", venue_rows=10)

        repo.create.assert_called_once()
        kwargs = repo.create.call_args.kwargs
        assert kwargs["status"] == "draft"
        assert result.status == "draft"

    async def test_create_with_all_fields(self, svc, repo):
        """Create event with all optional fields."""
        mock_event = _mock_event(
            name="Gala",
            description="VIP Event",
            location="Grand Hotel",
            venue_rows=20,
            venue_cols=15,
            layout_type="banquet",
        )
        repo.create.return_value = mock_event

        result = await svc.create_event(
            name="Gala",
            description="VIP Event",
            location="Grand Hotel",
            venue_rows=20,
            venue_cols=15,
            layout_type="banquet",
        )

        assert result.name == "Gala"
        assert result.venue_rows == 20
        assert result.layout_type == "banquet"

    async def test_create_returns_event(self, svc, repo):
        """Create returns the created event object."""
        mock_event = _mock_event(id=uuid.uuid4())
        repo.create.return_value = mock_event

        result = await svc.create_event(name="Test")

        assert result.id == mock_event.id
        assert isinstance(result, MagicMock)


class TestEventServiceGet:
    """Test event retrieval."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    async def test_get_event_found(self, svc, repo):
        """Get returns event when found."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(id=event_id, name="Found Event")
        repo.get_by_id.return_value = mock_event

        result = await svc.get_event(event_id)

        repo.get_by_id.assert_called_once_with(event_id)
        assert result.id == event_id
        assert result.name == "Found Event"

    async def test_get_event_not_found_raises(self, svc, repo):
        """Get raises EventNotFoundError when event doesn't exist."""
        event_id = uuid.uuid4()
        repo.get_by_id.return_value = None

        with pytest.raises(EventNotFoundError, match=str(event_id)):
            await svc.get_event(event_id)

    async def test_get_event_not_found_message_includes_id(self, svc, repo):
        """Error message includes the event ID."""
        event_id = uuid.uuid4()
        repo.get_by_id.return_value = None

        with pytest.raises(EventNotFoundError) as exc_info:
            await svc.get_event(event_id)

        assert str(event_id) in str(exc_info.value)


class TestEventServiceList:
    """Test event listing."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    async def test_list_all_without_filter(self, svc, repo):
        """List without status filter returns all events."""
        mock_events = [
            _mock_event(status="draft"),
            _mock_event(status="active"),
            _mock_event(status="completed"),
        ]
        repo.list_all.return_value = mock_events

        result = await svc.list_events()

        repo.list_all.assert_called_once()
        repo.get_by_status.assert_not_called()
        assert len(result) == 3

    async def test_list_with_status_filter(self, svc, repo):
        """List with status filter returns only matching events."""
        mock_events = [
            _mock_event(status="active"),
            _mock_event(status="active"),
        ]
        repo.get_by_status.return_value = mock_events

        result = await svc.list_events(status="active")

        repo.get_by_status.assert_called_once_with("active")
        repo.list_all.assert_not_called()
        assert len(result) == 2
        assert all(e.status == "active" for e in result)

    async def test_list_draft_events(self, svc, repo):
        """Filter by draft status."""
        mock_events = [_mock_event(status="draft")]
        repo.get_by_status.return_value = mock_events

        result = await svc.list_events(status="draft")

        repo.get_by_status.assert_called_once_with("draft")
        assert len(result) == 1

    async def test_list_empty_returns_empty(self, svc, repo):
        """Empty list returns empty list."""
        repo.list_all.return_value = []

        result = await svc.list_events()

        assert result == []

    async def test_list_with_none_status_uses_list_all(self, svc, repo):
        """Passing status=None calls list_all, not get_by_status."""
        mock_events = [_mock_event()]
        repo.list_all.return_value = mock_events

        result = await svc.list_events(status=None)

        repo.list_all.assert_called_once()
        repo.get_by_status.assert_not_called()


class TestEventServiceUpdate:
    """Test event updates."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    async def test_update_non_status_fields(self, svc, repo):
        """Update name, location, etc. without status change."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft", name="Old Name")
        updated_event = _mock_event(status="draft", name="New Name")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(event_id, name="New Name")

        repo.update.assert_called_once_with(event_id, name="New Name")
        assert result.name == "New Name"

    async def test_update_with_valid_status_transition(self, svc, repo):
        """Update with valid status transition succeeds."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft")
        updated_event = _mock_event(status="active")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(event_id, status="active")

        repo.update.assert_called_once_with(event_id, status="active")
        assert result.status == "active"

    async def test_update_with_invalid_status_transition(self, svc, repo):
        """Update with invalid status transition raises error."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="completed")
        repo.get_by_id.return_value = mock_event

        with pytest.raises(InvalidStateTransitionError, match="Cannot transition"):
            await svc.update_event(event_id, status="active")

        repo.update.assert_not_called()

    async def test_update_not_found_raises(self, svc, repo):
        """Update raises when repo returns None."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = None

        with pytest.raises(EventNotFoundError):
            await svc.update_event(event_id, name="New")

    async def test_update_same_status_does_not_validate_transition(self, svc, repo):
        """Updating to same status doesn't trigger transition validation."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="active")
        updated_event = _mock_event(status="active", name="New Name")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(event_id, status="active", name="New Name")

        repo.update.assert_called_once()
        assert result.status == "active"

    async def test_update_multiple_fields(self, svc, repo):
        """Update multiple fields at once."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft")
        updated_event = _mock_event(
            status="draft", name="New Name", location="New Location"
        )
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(
            event_id, name="New Name", location="New Location"
        )

        repo.update.assert_called_once_with(
            event_id, name="New Name", location="New Location"
        )
        assert result.name == "New Name"
        assert result.location == "New Location"


class TestEventServiceStateTransitions:
    """Test valid and invalid state transitions."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    # Valid transitions
    async def test_transition_draft_to_active(self, svc, repo):
        """Draft → Active is valid."""
        mock_event = _mock_event(status="draft")
        updated_event = _mock_event(status="active")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(uuid.uuid4(), status="active")

        assert result.status == "active"

    async def test_transition_draft_to_cancelled(self, svc, repo):
        """Draft → Cancelled is valid."""
        mock_event = _mock_event(status="draft")
        updated_event = _mock_event(status="cancelled")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(uuid.uuid4(), status="cancelled")

        assert result.status == "cancelled"

    async def test_transition_active_to_completed(self, svc, repo):
        """Active → Completed is valid."""
        mock_event = _mock_event(status="active")
        updated_event = _mock_event(status="completed")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(uuid.uuid4(), status="completed")

        assert result.status == "completed"

    async def test_transition_active_to_cancelled(self, svc, repo):
        """Active → Cancelled is valid."""
        mock_event = _mock_event(status="active")
        updated_event = _mock_event(status="cancelled")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(uuid.uuid4(), status="cancelled")

        assert result.status == "cancelled"

    async def test_transition_cancelled_to_draft(self, svc, repo):
        """Cancelled → Draft is valid."""
        mock_event = _mock_event(status="cancelled")
        updated_event = _mock_event(status="draft")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = updated_event

        result = await svc.update_event(uuid.uuid4(), status="draft")

        assert result.status == "draft"

    # Invalid transitions
    async def test_invalid_transition_active_to_draft(self, svc, repo):
        """Active → Draft is invalid."""
        mock_event = _mock_event(status="active")
        repo.get_by_id.return_value = mock_event

        with pytest.raises(InvalidStateTransitionError):
            await svc.update_event(uuid.uuid4(), status="draft")

    async def test_invalid_transition_completed_to_active(self, svc, repo):
        """Completed → Active is invalid."""
        mock_event = _mock_event(status="completed")
        repo.get_by_id.return_value = mock_event

        with pytest.raises(InvalidStateTransitionError):
            await svc.update_event(uuid.uuid4(), status="active")

    async def test_invalid_transition_completed_to_cancelled(self, svc, repo):
        """Completed → Cancelled is invalid."""
        mock_event = _mock_event(status="completed")
        repo.get_by_id.return_value = mock_event

        with pytest.raises(InvalidStateTransitionError):
            await svc.update_event(uuid.uuid4(), status="cancelled")

    async def test_invalid_transition_completed_to_draft(self, svc, repo):
        """Completed → Draft is invalid."""
        mock_event = _mock_event(status="completed")
        repo.get_by_id.return_value = mock_event

        with pytest.raises(InvalidStateTransitionError):
            await svc.update_event(uuid.uuid4(), status="draft")


class TestEventServiceLifecycleMethods:
    """Test convenience methods: activate, complete, cancel."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    async def test_activate_event(self, svc, repo):
        """activate_event sets status to active."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft")
        activated = _mock_event(status="active")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = activated

        result = await svc.activate_event(event_id)

        repo.update.assert_called_once_with(event_id, status="active")
        assert result.status == "active"

    async def test_complete_event(self, svc, repo):
        """complete_event sets status to completed."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="active")
        completed = _mock_event(status="completed")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = completed

        result = await svc.complete_event(event_id)

        repo.update.assert_called_once_with(event_id, status="completed")
        assert result.status == "completed"

    async def test_cancel_event(self, svc, repo):
        """cancel_event sets status to cancelled."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft")
        cancelled = _mock_event(status="cancelled")
        repo.get_by_id.return_value = mock_event
        repo.update.return_value = cancelled

        result = await svc.cancel_event(event_id)

        repo.update.assert_called_once_with(event_id, status="cancelled")
        assert result.status == "cancelled"


class TestEventServiceDelete:
    """Test event deletion rules."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    async def test_delete_draft_succeeds(self, svc, repo):
        """Delete succeeds for draft events."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft")
        repo.get_by_id.return_value = mock_event
        repo.delete.return_value = True

        result = await svc.delete_event(event_id)

        repo.delete.assert_called_once_with(event_id)
        assert result is True

    async def test_delete_active_raises(self, svc, repo):
        """Delete raises for active events."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="active")
        repo.get_by_id.return_value = mock_event

        with pytest.raises(InvalidStateTransitionError, match="Only draft"):
            await svc.delete_event(event_id)

        repo.delete.assert_not_called()

    async def test_delete_completed_raises(self, svc, repo):
        """Delete raises for completed events."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="completed")
        repo.get_by_id.return_value = mock_event

        with pytest.raises(InvalidStateTransitionError, match="Only draft"):
            await svc.delete_event(event_id)

        repo.delete.assert_not_called()

    async def test_delete_cancelled_succeeds(self, svc, repo):
        """Delete succeeds for cancelled events."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="cancelled")
        repo.get_by_id.return_value = mock_event
        repo.delete.return_value = True

        result = await svc.delete_event(event_id)

        assert result is True
        repo.delete.assert_called_once_with(event_id)

    async def test_delete_not_found_raises(self, svc, repo):
        """Delete raises EventNotFoundError if event doesn't exist."""
        event_id = uuid.uuid4()
        repo.get_by_id.return_value = None

        with pytest.raises(EventNotFoundError):
            await svc.delete_event(event_id)

    async def test_delete_returns_repo_result(self, svc, repo):
        """Delete returns the result from repo.delete()."""
        event_id = uuid.uuid4()
        mock_event = _mock_event(status="draft")
        repo.get_by_id.return_value = mock_event
        repo.delete.return_value = True

        result = await svc.delete_event(event_id)

        assert result is True


class TestEventServiceDuplicate:
    """Test event duplication."""

    @pytest.fixture
    def repo(self):
        return AsyncMock()

    @pytest.fixture
    def svc(self, repo):
        return EventService(repo)

    async def test_duplicate_creates_copy(self, svc, repo):
        """Duplicate creates a new event with (Copy) suffix."""
        event_id = uuid.uuid4()
        source = _mock_event(
            name="Annual Meeting",
            description="Main event",
            location="Venue A",
            venue_rows=10,
            venue_cols=8,
            layout_type="theater",
        )
        copy = _mock_event(
            name="Annual Meeting (Copy)",
            description="Main event",
            location="Venue A",
            venue_rows=10,
            venue_cols=8,
            layout_type="theater",
            status="draft",
        )
        repo.get_by_id.return_value = source
        repo.create.return_value = copy

        result = await svc.duplicate_event(event_id)

        # Verify create was called with correct args
        repo.create.assert_called_once()
        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["name"] == "Annual Meeting (Copy)"
        assert call_kwargs["description"] == "Main event"
        assert call_kwargs["location"] == "Venue A"
        assert call_kwargs["venue_rows"] == 10
        assert call_kwargs["venue_cols"] == 8
        assert call_kwargs["layout_type"] == "theater"
        assert call_kwargs["status"] == "draft"
        assert result.name == "Annual Meeting (Copy)"

    async def test_duplicate_copies_config(self, svc, repo):
        """Duplicate copies the config dict."""
        event_id = uuid.uuid4()
        config = {"allow_self_checkin": True, "require_approval": False}
        source = _mock_event(config=config)
        copy = _mock_event(config=config, status="draft")
        repo.get_by_id.return_value = source
        repo.create.return_value = copy

        result = await svc.duplicate_event(event_id)

        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["config"] == config

    async def test_duplicate_empty_config(self, svc, repo):
        """Duplicate handles None config as empty dict."""
        event_id = uuid.uuid4()
        source = _mock_event(config=None)
        copy = _mock_event(config={}, status="draft")
        repo.get_by_id.return_value = source
        repo.create.return_value = copy

        result = await svc.duplicate_event(event_id)

        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["config"] == {}

    async def test_duplicate_new_event_always_draft(self, svc, repo):
        """Duplicated event is always draft, regardless of source status."""
        event_id = uuid.uuid4()
        source = _mock_event(status="active", name="Active Event")
        copy = _mock_event(status="draft", name="Active Event (Copy)")
        repo.get_by_id.return_value = source
        repo.create.return_value = copy

        result = await svc.duplicate_event(event_id)

        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["status"] == "draft"
        assert result.status == "draft"

    async def test_duplicate_source_not_found_raises(self, svc, repo):
        """Duplicate raises if source event doesn't exist."""
        event_id = uuid.uuid4()
        repo.get_by_id.return_value = None

        with pytest.raises(EventNotFoundError):
            await svc.duplicate_event(event_id)

    async def test_duplicate_preserves_all_venue_fields(self, svc, repo):
        """Duplicate copies all venue-related fields."""
        event_id = uuid.uuid4()
        source = _mock_event(
            name="Banquet",
            description="Formal dinner",
            location="Grand Hall",
            venue_rows=15,
            venue_cols=20,
            layout_type="banquet",
        )
        copy = _mock_event(status="draft")
        repo.get_by_id.return_value = source
        repo.create.return_value = copy

        await svc.duplicate_event(event_id)

        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["venue_rows"] == 15
        assert call_kwargs["venue_cols"] == 20
        assert call_kwargs["layout_type"] == "banquet"
