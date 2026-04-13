"""LLM factory — provider-based chat model creation.

Supports multiple providers per tier.  Each tier (fast/smart/strong/max)
maps to a provider + model + api_key + base_url.  The mapping can be
changed at runtime via agent_config.json ``_llm_providers`` overrides.

Providers:
    deepseek  — OpenAI-compatible (default fast)
    openai    — OpenAI native (default smart)
    anthropic — Anthropic native (default strong/max)
    glm       — 智谱 GLM, OpenAI-compatible
    qwen      — 通义千问, DashScope OpenAI-compatible
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.config import settings

logger = logging.getLogger(__name__)

# ── Provider registry ─────────────────────────────────────────

# Each provider knows how to create a BaseChatModel from a config dict.
# Config dict keys: model, api_key, base_url, temperature, max_tokens.

AVAILABLE_PROVIDERS = ("deepseek", "openai", "anthropic", "glm", "qwen")


def _create_openai_compatible(cfg: dict[str, Any]) -> BaseChatModel:
    """Create a ChatOpenAI instance (works for OpenAI, DeepSeek, GLM, Qwen)."""
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": cfg["model"],
        "api_key": cfg["api_key"],
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 4096),
    }
    if cfg.get("base_url"):
        kwargs["base_url"] = cfg["base_url"]
    return ChatOpenAI(**kwargs)


def _create_anthropic(cfg: dict[str, Any]) -> BaseChatModel:
    """Create a ChatAnthropic instance."""
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=cfg["model"],
        api_key=cfg["api_key"],
        temperature=cfg.get("temperature", 0.3),
        max_tokens=cfg.get("max_tokens", 4096),
        timeout=cfg.get("timeout", 120.0),
    )


_PROVIDER_FACTORIES: dict[str, Any] = {
    "deepseek": _create_openai_compatible,
    "openai": _create_openai_compatible,
    "glm": _create_openai_compatible,
    "qwen": _create_openai_compatible,
    "anthropic": _create_anthropic,
}


# ── Default provider configs from .env ────────────────────────

def _env_provider_defaults() -> dict[str, dict[str, Any]]:
    """Build default provider config per tier from env vars."""
    return {
        "fast": {
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "api_key": settings.deepseek_api_key,
            "base_url": settings.deepseek_base_url,
            "temperature": 0.3,
            "max_tokens": 4096,
        },
        "smart": {
            "provider": "openai",
            "model": settings.openai_model,
            "api_key": settings.openai_api_key,
            "base_url": "",
            "temperature": 0.3,
            "max_tokens": 4096,
        },
        "strong": {
            "provider": "anthropic",
            "model": settings.anthropic_model,
            "api_key": settings.anthropic_api_key,
            "base_url": "",
            "temperature": 0.3,
            "max_tokens": 4096,
        },
        "max": {
            "provider": "anthropic",
            "model": settings.anthropic_max_model,
            "api_key": settings.anthropic_api_key,
            "base_url": "",
            "temperature": 0,
            "max_tokens": 16384,
            "timeout": 120.0,
        },
    }


def _get_provider_config(tier: str) -> dict[str, Any]:
    """Get merged provider config for a tier (env defaults + JSON overrides)."""
    defaults = _env_provider_defaults()
    base = defaults.get(tier, defaults["smart"]).copy()

    # Layer on JSON overrides from agent_config.json
    try:
        from app.services.agent_config_service import _read_overrides
        overrides = _read_overrides()
        llm_over = overrides.get("_llm_providers", {}).get(tier, {})
        for key in ("provider", "model", "api_key", "base_url"):
            if key in llm_over and llm_over[key]:
                base[key] = llm_over[key]
        # When provider is overridden, fill in defaults for that provider
        if "provider" in llm_over and llm_over["provider"] != base.get("_orig_provider"):
            provider = llm_over["provider"]
            prov_defaults = _provider_env_defaults(provider)
            # Only fill in fields not explicitly overridden
            for key in ("model", "api_key", "base_url"):
                if key not in llm_over and key in prov_defaults:
                    base[key] = prov_defaults[key]
    except Exception:
        pass  # Use env defaults on any error

    return base


def _provider_env_defaults(provider: str) -> dict[str, str]:
    """Get env-based defaults for a specific provider (for auto-fill on switch)."""
    mapping: dict[str, dict[str, str]] = {
        "deepseek": {
            "model": settings.deepseek_model,
            "api_key": settings.deepseek_api_key,
            "base_url": settings.deepseek_base_url,
        },
        "openai": {
            "model": settings.openai_model,
            "api_key": settings.openai_api_key,
            "base_url": "",
        },
        "anthropic": {
            "model": settings.anthropic_model,
            "api_key": settings.anthropic_api_key,
            "base_url": "",
        },
        "glm": {
            "model": settings.glm_model,
            "api_key": settings.glm_api_key,
            "base_url": settings.glm_base_url,
        },
        "qwen": {
            "model": settings.qwen_model,
            "api_key": settings.qwen_api_key,
            "base_url": settings.qwen_base_url,
        },
    }
    return mapping.get(provider, {})


def _is_key_valid(key: str) -> bool:
    """Check if an API key looks configured (not placeholder)."""
    return bool(key and key not in ("", "sk-xxx", "sk-ant-xxx", "xxx"))


# ── Fallback chain ────────────────────────────────────────────

_FALLBACK_ORDER = ["max", "strong", "smart", "fast"]


def _find_working_tier(requested: str) -> str:
    """Find the first tier at or below the requested level that has a valid key."""
    start = _FALLBACK_ORDER.index(requested) if requested in _FALLBACK_ORDER else 0
    for tier in _FALLBACK_ORDER[start:]:
        cfg = _get_provider_config(tier)
        if _is_key_valid(cfg.get("api_key", "")):
            return tier
    raise ValueError(
        "No LLM provider configured. Set at least one API key "
        "(DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, "
        "GLM_API_KEY, or QWEN_API_KEY) in .env"
    )


# ── Public API ────────────────────────────────────────────────

def create_llm(tier: str | None = None) -> BaseChatModel:
    """Create a LangChain chat model for the given tier.

    Falls back through tiers if the configured provider's key is missing:
    max -> strong -> smart -> fast.

    Args:
        tier: 'fast', 'smart', 'strong', or 'max'.
            Defaults to settings.llm_default_tier.

    Returns:
        A LangChain BaseChatModel instance.

    Raises:
        ValueError: If no LLM provider is configured at all.
    """
    tier = tier or settings.llm_default_tier

    # Resolve to a tier with a valid key
    effective_tier = _find_working_tier(tier)
    if effective_tier != tier:
        logger.info("Tier %s unavailable, falling back to %s", tier, effective_tier)

    cfg = _get_provider_config(effective_tier)
    provider = cfg.get("provider", "openai")
    factory = _PROVIDER_FACTORIES.get(provider)
    if not factory:
        raise ValueError(f"Unknown LLM provider: {provider}")

    logger.debug(
        "Creating LLM: tier=%s provider=%s model=%s",
        effective_tier, provider, cfg.get("model"),
    )
    return factory(cfg)


@lru_cache(maxsize=8)
def get_llm(tier: str = "smart") -> BaseChatModel:
    """Cached LLM getter — reuses instances per tier."""
    return create_llm(tier)


def list_available_providers() -> list[dict[str, str]]:
    """Return all providers that have a valid API key configured."""
    result = []
    for provider in AVAILABLE_PROVIDERS:
        defaults = _provider_env_defaults(provider)
        key = defaults.get("api_key", "")
        result.append({
            "provider": provider,
            "label": {
                "deepseek": "DeepSeek",
                "openai": "OpenAI",
                "anthropic": "Anthropic",
                "glm": "GLM (智谱)",
                "qwen": "Qwen (通义千问)",
            }.get(provider, provider),
            "model": defaults.get("model", ""),
            "base_url": defaults.get("base_url", ""),
            "has_key": _is_key_valid(key),
        })
    return result
