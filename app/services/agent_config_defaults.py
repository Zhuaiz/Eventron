"""Register built-in defaults for every agent plugin.

Called once at app startup to populate ``agent_config_service._DEFAULTS``.
Imports each plugin's prompt constant directly — no runtime cost beyond
the initial import.
"""

from __future__ import annotations


def register_all_defaults() -> None:
    """Register hardcoded defaults for all plugins + orchestrator."""
    from app.services.agent_config_service import register_default

    # ── Orchestrator ────────────────────────────────────────────
    from agents.orchestrator import ORCHESTRATOR_DEFAULT_PROMPT
    register_default(
        "orchestrator",
        model_tier="smart",
        system_prompt=ORCHESTRATOR_DEFAULT_PROMPT,
    )

    # ── Identity ────────────────────────────────────────────────
    from agents.plugins.identity import _NAME_EXTRACT_PROMPT
    register_default(
        "identity",
        model_tier="fast",
        system_prompt=_NAME_EXTRACT_PROMPT,
    )

    # ── Organizer ───────────────────────────────────────────────
    from agents.plugins.organizer import ORGANIZER_SYSTEM
    register_default(
        "organizer",
        model_tier="smart",
        system_prompt=ORGANIZER_SYSTEM,
    )

    # ── Seating ─────────────────────────────────────────────────
    from agents.plugins.seating import _SYSTEM as SEATING_SYSTEM
    register_default(
        "seating",
        model_tier="smart",
        system_prompt=SEATING_SYSTEM,
    )

    # ── Change ──────────────────────────────────────────────────
    from agents.plugins.change import _CHANGE_SYSTEM
    register_default(
        "change",
        model_tier="smart",
        system_prompt=_CHANGE_SYSTEM,
    )

    # ── Planner ─────────────────────────────────────────────────
    from agents.plugins.planner import PLANNER_SYSTEM
    register_default(
        "planner",
        model_tier="strong",
        system_prompt=PLANNER_SYSTEM,
    )

    # ── Pagegen ─────────────────────────────────────────────────
    from agents.plugins.pagegen import _PAGEGEN_SYSTEM
    register_default(
        "pagegen",
        model_tier="strong",
        system_prompt=_PAGEGEN_SYSTEM,
        gen_model_tier="max",
    )

    # ── Badge ───────────────────────────────────────────────────
    from agents.plugins.badge import _BADGE_SYSTEM
    register_default(
        "badge",
        model_tier="smart",
        system_prompt=_BADGE_SYSTEM,
    )

    # ── Checkin ─────────────────────────────────────────────────
    register_default(
        "checkin",
        model_tier="fast",
        system_prompt="",  # No system prompt
    )

    # ── Guide ───────────────────────────────────────────────────
    register_default(
        "guide",
        model_tier="fast",
        system_prompt="",  # No system prompt
    )
