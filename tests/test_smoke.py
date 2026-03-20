"""Smoke tests — verify project skeleton is wired correctly."""


class TestProjectSkeleton:
    """Phase 0 checkpoint: everything imports and health endpoint works."""

    def test_config_loads(self):
        """Settings can be instantiated with defaults."""
        from app.config import Settings

        s = Settings()
        assert s.app_name == "Eventron"
        assert s.llm_default_tier in ("fast", "smart", "strong")

    def test_base_model_exists(self):
        """ORM Base and mixins are importable."""
        from app.models.base import Base, TimestampMixin, UUIDMixin

        assert Base is not None
        assert UUIDMixin is not None
        assert TimestampMixin is not None

    def test_app_creates(self):
        """FastAPI app factory runs without errors."""
        from app.main import create_app

        app = create_app()
        assert app.title == "Eventron"

    async def test_health_endpoint(self, client):
        """GET /health returns 200."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_factories_produce_valid_data(self):
        """Test data factories return expected structures."""
        from tests.factories import make_attendee, make_event, make_seat_grid

        att = make_attendee(name="李四", role="甲方嘉宾")
        assert att["name"] == "李四"
        assert att["role"] == "甲方嘉宾"

        ev = make_event(venue_rows=5, venue_cols=3)
        assert ev["venue_rows"] == 5

        grid = make_seat_grid(2, 3)
        assert len(grid) == 6
        assert grid[0]["label"] == "A1"
