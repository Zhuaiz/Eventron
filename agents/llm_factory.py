"""Per-agent LLM factory — different agents use different models.

Principle: 能用 fast 的不用 smart，能用 smart 的不用 strong。省钱、省延迟。
Auto-fallback: if a tier's API key is not configured, falls back to one that is.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.config import settings

logger = logging.getLogger(__name__)

# ── Model tier definitions ───────────────────────────────────
LLM_TIERS: dict[str, dict[str, str]] = {
    "fast": {
        "provider": "deepseek",
        "model": settings.deepseek_model,
        "api_key": settings.deepseek_api_key,
        "base_url": settings.deepseek_base_url,
    },
    "smart": {
        "provider": "openai",
        "model": settings.openai_model,
        "api_key": settings.openai_api_key,
    },
    "strong": {
        "provider": "anthropic",
        "model": settings.anthropic_model,
        "api_key": settings.anthropic_api_key,
    },
    "max": {
        "provider": "anthropic",
        "model": settings.anthropic_max_model,
        "api_key": settings.anthropic_api_key,
    },
}

# ── Per-plugin recommended tier ──────────────────────────────
PLUGIN_LLM_MAP: dict[str, str] = {
    "orchestrator": "fast",
    "identity": "fast",
    "seating": "smart",
    "checkin": "fast",
    "change": "smart",
    "pagegen": "strong",
    "badge": "fast",
    "guide": "fast",
}

# Fallback order: try these tiers in sequence if the preferred one has no key
_FALLBACK_ORDER = ["fast", "smart", "strong", "max"]


def _has_valid_key(tier: dict[str, str]) -> bool:
    """Check if a tier has a real API key (not empty or placeholder)."""
    key = tier.get("api_key", "")
    return bool(key) and key not in ("sk-xxx", "sk-ant-xxx", "")


def _resolve_tier(preferred: str) -> dict[str, str]:
    """Get the preferred tier, or fall back to one that has a valid key."""
    tier = LLM_TIERS.get(preferred)
    if tier and _has_valid_key(tier):
        return tier

    # Fallback: find the first tier with a valid key
    for name in _FALLBACK_ORDER:
        t = LLM_TIERS[name]
        if _has_valid_key(t):
            if name != preferred:
                logger.info(f"LLM tier '{preferred}' not configured, falling back to '{name}'")
            return t

    raise RuntimeError(
        "No LLM API key configured! Set at least one of: "
        "DEEPSEEK_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY"
    )


def get_llm(plugin_name: str | None = None) -> BaseChatModel:
    """Get the appropriate LLM for a plugin.

    Auto-falls back to a configured tier if the preferred one has no API key.

    Args:
        plugin_name: Plugin name to look up tier. None = use default.

    Returns:
        A LangChain BaseChatModel instance.
    """
    tier_name = PLUGIN_LLM_MAP.get(plugin_name or "", settings.llm_default_tier)
    tier = _resolve_tier(tier_name)

    provider = tier["provider"]

    if provider in ("openai", "deepseek"):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": tier["model"],
            "api_key": tier["api_key"],
            "temperature": 0,
            "max_tokens": 4096,
            "timeout": 120,
        }
        if tier.get("base_url"):
            kwargs["base_url"] = tier["base_url"]
        return ChatOpenAI(**kwargs)

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Max tier gets larger token budget for full-page generation
        is_max = tier["model"] == settings.anthropic_max_model
        tokens = 16384 if is_max else 8192
        return ChatAnthropic(
            model=tier["model"],
            api_key=tier["api_key"],
            temperature=0,
            max_tokens=tokens,
            timeout=120.0,
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
