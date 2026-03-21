"""Abstract base class for all pluggable sub-agents.

Every agent plugin MUST inherit from AgentPlugin and implement all
abstract properties and methods. No exceptions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from agents.state import AgentState


class AgentPlugin(ABC):
    """Base class for all pluggable sub-agents.

    Plugins receive a ``services`` dict at construction time that gives
    them access to the application service layer (EventService,
    SeatingService, AttendeeService, etc.) without importing or
    constructing them directly.
    """

    def __init__(self, services: dict[str, Any] | None = None):
        self._services = services or {}

    # ── Convenience accessors for common services ──────────────
    @property
    def event_svc(self):
        return self._services.get("event")

    @property
    def seat_svc(self):
        return self._services.get("seating")

    @property
    def attendee_svc(self):
        return self._services.get("attendee")

    def get_llm(self, tier: str | None = None):
        """Get an LLM instance for the requested tier.

        If no explicit tier is given, checks agent_config overrides
        before falling back to the plugin's hardcoded ``llm_model``.
        """
        if not tier:
            tier = self._effective_tier()
        factory = self._services.get("llm_factory")
        if factory:
            return factory(tier or "smart")
        return None

    def _effective_tier(self) -> str:
        """Return model tier with config override support."""
        try:
            from app.services.agent_config_service import (
                get_effective_tier,
            )
            return get_effective_tier(self.name)
        except Exception:
            return self.llm_model or "smart"

    def _effective_prompt(self, default: str) -> str:
        """Return system prompt with config override support."""
        try:
            from app.services.agent_config_service import (
                get_effective_prompt,
            )
            prompt = get_effective_prompt(self.name)
            return prompt if prompt else default
        except Exception:
            return default

    @staticmethod
    def get_event_files(
        event_id: str, file_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Look up files from the event's file store.

        Args:
            event_id: UUID string of the event.
            file_type: Optional filter — 'excel', 'image', 'pdf'.

        Returns:
            List of file entries with 'path', 'filename', 'type' keys.
        """
        try:
            from tools.event_files import (
                find_files_by_type,
                load_manifest,
                event_dir,
            )
            if file_type:
                return find_files_by_type(event_id, file_type)
            manifest = load_manifest(event_id)
            edir = event_dir(event_id)
            return [
                {**e, "path": str(edir / e["stored_name"])}
                for e in manifest
                if (edir / e["stored_name"]).exists()
            ]
        except Exception:
            return []

    # ── Abstract interface ─────────────────────────────────────
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name, e.g. 'seating', 'checkin'."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description for the orchestrator's routing prompt."""

    @property
    @abstractmethod
    def intent_keywords(self) -> list[str]:
        """Keywords that hint at this plugin's domain.
        Used by orchestrator to build the intent classification prompt."""

    @property
    @abstractmethod
    def tools(self) -> list[BaseTool]:
        """LangChain tools this agent can call."""

    @abstractmethod
    async def handle(self, state: AgentState) -> dict[str, Any]:
        """Process the user's request given current state.
        Returns a dict to merge into AgentState."""

    @property
    def requires_identity(self) -> bool:
        """If True, orchestrator ensures user is identified before routing here."""
        return True

    @property
    def enabled(self) -> bool:
        """Can be toggled via config. Disabled plugins are invisible to orchestrator."""
        return True

    @property
    def llm_model(self) -> str | None:
        """Override LLM model for this plugin. None = use default.
        Each plugin can declare the model best suited for its task complexity."""
        return None
