"""Agent configuration API — manage plugin prompts, models, and state.

Routes:
    GET  /agent-config           → list all plugin configs
    GET  /agent-config/{name}    → get one plugin's config
    PATCH /agent-config/{name}   → update (partial)
    POST /agent-config/{name}/reset → revert to defaults
    GET  /llm-providers          → list all LLM tier configs
    PATCH /llm-providers/{tier}  → update one tier
    POST /llm-providers/reset    → reset all to .env defaults
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import agent_config_service as svc

router = APIRouter()


class AgentConfigPatch(BaseModel):
    """Partial update for a plugin's config."""
    model_tier: str | None = Field(
        None, description="LLM tier: fast/smart/strong/max",
    )
    system_prompt: str | None = Field(
        None, description="System prompt override (empty to reset)",
    )
    enabled: bool | None = Field(
        None, description="Enable/disable this plugin",
    )
    gen_model_tier: str | None = Field(
        None,
        description="Generation-specific LLM tier (pagegen only)",
    )


@router.get("/agent-config")
async def list_configs() -> list[dict[str, Any]]:
    """List all agent plugin configurations."""
    return await svc.list_agent_configs()


@router.get("/agent-config/{name}")
async def get_config(name: str) -> dict[str, Any]:
    """Get a single plugin's configuration."""
    result = await svc.get_agent_config(name)
    if not result:
        raise HTTPException(404, f"Plugin '{name}' not found")
    return result


@router.patch("/agent-config/{name}")
async def update_config(
    name: str, body: AgentConfigPatch,
) -> dict[str, Any]:
    """Update a plugin's configuration (partial patch)."""
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "No fields to update")
    try:
        return await svc.update_agent_config(name, patch)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/agent-config/{name}/reset")
async def reset_config(name: str) -> dict[str, Any]:
    """Reset a plugin's configuration to built-in defaults."""
    try:
        return await svc.reset_agent_config(name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# ── LLM Provider endpoints ─────────────────────────────────────

class LLMProviderPatch(BaseModel):
    """Partial update for an LLM tier."""
    model: str | None = Field(None, description="Model name")
    api_key: str | None = Field(None, description="API key")
    base_url: str | None = Field(None, description="Base URL override")
    provider: str | None = Field(None, description="Provider name")


@router.get("/llm-providers/models")
async def available_models() -> dict[str, Any]:
    """Return known models grouped by provider.

    Frontend uses this to populate the model-name dropdown so users
    don't have to memorize model ID strings.
    """
    return svc.get_available_models()


@router.get("/llm-providers")
async def list_llm_providers() -> dict[str, Any]:
    """List all LLM tier configurations (keys masked)."""
    return await svc.get_llm_providers()


@router.patch("/llm-providers/{tier}")
async def update_llm_provider(
    tier: str, body: LLMProviderPatch,
) -> dict[str, Any]:
    """Update one LLM tier's config."""
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(422, "No fields to update")
    try:
        return await svc.update_llm_provider(tier, patch)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/llm-providers/reset")
async def reset_llm_providers() -> dict[str, Any]:
    """Reset all LLM provider configs to .env defaults."""
    return await svc.reset_llm_providers()


@router.get("/llm-providers/available")
async def list_available_providers() -> list[dict[str, Any]]:
    """List all known providers with their env-configured status."""
    from app.llm_factory import list_available_providers
    return list_available_providers()
