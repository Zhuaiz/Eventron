"""FastAPI application factory."""

import pathlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings

# Vite build output directory
_WEB_DIST = pathlib.Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown hooks."""
    # Startup: register agent plugin config defaults
    from app.services.agent_config_defaults import register_all_defaults
    register_all_defaults()
    yield
    # Shutdown: close connections


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="会场智能排座 Multi-Agent 系统",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ── CORS (for organizer portal SPA) ───────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── CRUD Routers ──────────────────────────────────────────
    from app.api.approvals import router as approvals_router
    from app.api.attendees import router as attendees_router
    from app.api.events import router as events_router
    from app.api.seats import router as seats_router
    from app.api.venue_areas import router as venue_areas_router

    app.include_router(events_router, prefix="/api/events", tags=["events"])
    app.include_router(seats_router, prefix="/api/events", tags=["seats"])
    app.include_router(attendees_router, prefix="/api/events", tags=["attendees"])
    app.include_router(approvals_router, prefix="/api/events", tags=["approvals"])
    app.include_router(venue_areas_router, prefix="/api/events", tags=["venue-areas"])

    # ── Organizer Portal API (v1) ─────────────────────────────
    from app.api.agent_chat import router as agent_chat_router
    from app.api.auth import router as auth_router
    from app.api.badge_templates import router as badge_template_router
    from app.api.dashboard import router as dashboard_router
    from app.api.event_files import router as event_files_router
    from app.api.export import router as export_router
    from app.api.import_attendees import router as import_router

    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
    app.include_router(import_router, prefix="/api/v1", tags=["import"])
    app.include_router(
        badge_template_router, prefix="/api/v1/badge-templates", tags=["badge-templates"]
    )
    app.include_router(export_router, prefix="/api/v1", tags=["export"])
    app.include_router(event_files_router, prefix="/api/v1", tags=["event-files"])
    app.include_router(agent_chat_router, prefix="/api/v1/agent", tags=["agent"])

    from app.api.agent_config import router as agent_config_router
    app.include_router(
        agent_config_router, prefix="/api/v1", tags=["agent-config"],
    )

    # ── Public Routes (no JWT) ──────────────────────────────────
    from app.api.public_checkin import router as public_checkin_router

    app.include_router(
        public_checkin_router,
        prefix="/p/{event_id}",
        tags=["public-checkin"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # ── Serve frontend static files (production) ─────────────
    if _WEB_DIST.is_dir():
        from fastapi.responses import FileResponse

        app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="static")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            """Catch-all: serve index.html for SPA client-side routing."""
            file = _WEB_DIST / full_path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(_WEB_DIST / "index.html")

    return app


app = create_app()
