"""Agent configuration service — read/write per-plugin settings.

Stores agent prompts, model tiers, and enabled state in a JSON file
under ``data/agent_config.json``.  Defaults come from each plugin's
hardcoded constants; overrides are layered on top.

Thread-safe: uses an asyncio lock for write operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path("data")
_CONFIG_FILE = _CONFIG_DIR / "agent_config.json"
_write_lock = asyncio.Lock()

# ── Built-in defaults (populated at import time) ───────────────
# Each entry: { "model_tier": str, "system_prompt": str, "enabled": bool }
_DEFAULTS: dict[str, dict[str, Any]] = {}


def register_default(
    plugin_name: str,
    *,
    model_tier: str = "smart",
    system_prompt: str = "",
    enabled: bool = True,
    gen_model_tier: str | None = None,
) -> None:
    """Register a plugin's built-in defaults (called once per plugin)."""
    entry: dict[str, Any] = {
        "model_tier": model_tier,
        "system_prompt": system_prompt,
        "enabled": enabled,
    }
    if gen_model_tier:
        entry["gen_model_tier"] = gen_model_tier
    _DEFAULTS[plugin_name] = entry


def _read_overrides() -> dict[str, dict[str, Any]]:
    """Read user overrides from disk (sync, for speed)."""
    if not _CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(_CONFIG_FILE.read_text("utf-8"))
    except Exception:
        logger.warning("Failed to read agent config, using defaults")
        return {}


def _write_overrides(data: dict[str, dict[str, Any]]) -> None:
    """Write overrides to disk (sync helper, called inside lock)."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Public API ──────────────────────────────────────────────────

# Valid model tiers the UI can select
VALID_TIERS = ("fast", "smart", "strong", "max")


async def list_agent_configs() -> list[dict[str, Any]]:
    """Return config for every registered plugin.

    Merges defaults with user overrides.  Result list is sorted by
    plugin name for stable UI ordering.
    """
    overrides = _read_overrides()
    result: list[dict[str, Any]] = []
    for name in sorted(_DEFAULTS):
        default = _DEFAULTS[name]
        over = overrides.get(name, {})
        result.append({
            "name": name,
            "model_tier": over.get("model_tier", default["model_tier"]),
            "system_prompt": over.get(
                "system_prompt", default["system_prompt"],
            ),
            "enabled": over.get("enabled", default["enabled"]),
            "default_model_tier": default["model_tier"],
            "default_prompt_preview": default["system_prompt"][:200],
            "has_custom_prompt": "system_prompt" in over,
            "gen_model_tier": over.get(
                "gen_model_tier",
                default.get("gen_model_tier", ""),
            ),
            "default_gen_model_tier": default.get(
                "gen_model_tier", "",
            ),
        })
    return result


async def get_agent_config(plugin_name: str) -> dict[str, Any]:
    """Get full config for a single plugin (defaults + overrides)."""
    default = _DEFAULTS.get(plugin_name)
    if not default:
        return {}
    overrides = _read_overrides()
    over = overrides.get(plugin_name, {})
    return {
        "name": plugin_name,
        "model_tier": over.get("model_tier", default["model_tier"]),
        "system_prompt": over.get(
            "system_prompt", default["system_prompt"],
        ),
        "enabled": over.get("enabled", default["enabled"]),
        "default_model_tier": default["model_tier"],
        "default_system_prompt": default["system_prompt"],
        "has_custom_prompt": "system_prompt" in over,
        "gen_model_tier": over.get(
            "gen_model_tier",
            default.get("gen_model_tier", ""),
        ),
        "default_gen_model_tier": default.get(
            "gen_model_tier", "",
        ),
    }


async def update_agent_config(
    plugin_name: str, patch: dict[str, Any],
) -> dict[str, Any]:
    """Update one plugin's config.  Only supplied keys are changed.

    Accepted keys: model_tier, system_prompt, enabled, gen_model_tier.
    Set system_prompt to empty string to revert to default.
    """
    if plugin_name not in _DEFAULTS:
        raise ValueError(f"Unknown plugin: {plugin_name}")

    async with _write_lock:
        overrides = _read_overrides()
        current = overrides.get(plugin_name, {})

        if "model_tier" in patch:
            tier = patch["model_tier"]
            if tier not in VALID_TIERS:
                raise ValueError(
                    f"Invalid tier '{tier}', must be one of {VALID_TIERS}"
                )
            current["model_tier"] = tier

        if "system_prompt" in patch:
            prompt = patch["system_prompt"]
            if prompt:
                current["system_prompt"] = prompt
            else:
                # Empty string = revert to default
                current.pop("system_prompt", None)

        if "enabled" in patch:
            current["enabled"] = bool(patch["enabled"])

        if "gen_model_tier" in patch:
            tier = patch["gen_model_tier"]
            if tier and tier not in VALID_TIERS:
                raise ValueError(
                    f"Invalid tier '{tier}', must be one of {VALID_TIERS}"
                )
            if tier:
                current["gen_model_tier"] = tier
            else:
                current.pop("gen_model_tier", None)

        if current:
            overrides[plugin_name] = current
        else:
            overrides.pop(plugin_name, None)

        _write_overrides(overrides)

    return await get_agent_config(plugin_name)


async def reset_agent_config(plugin_name: str) -> dict[str, Any]:
    """Reset a plugin's config to defaults (remove all overrides)."""
    if plugin_name not in _DEFAULTS:
        raise ValueError(f"Unknown plugin: {plugin_name}")

    async with _write_lock:
        overrides = _read_overrides()
        overrides.pop(plugin_name, None)
        _write_overrides(overrides)

    return await get_agent_config(plugin_name)


# ── LLM Provider Configuration ──────────────────────────────────
# Stored in the same JSON file under a "_llm_providers" key.

_LLM_FILE = _CONFIG_DIR / "agent_config.json"


def _llm_defaults() -> dict[str, dict[str, str]]:
    """Return current .env-based LLM provider defaults per tier."""
    from app.config import settings
    return {
        "fast": {
            "label": "Fast",
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "api_key": settings.deepseek_api_key,
            "base_url": settings.deepseek_base_url,
        },
        "smart": {
            "label": "Smart",
            "provider": "openai",
            "model": settings.openai_model,
            "api_key": settings.openai_api_key,
            "base_url": "",
        },
        "strong": {
            "label": "Strong",
            "provider": "anthropic",
            "model": settings.anthropic_model,
            "api_key": settings.anthropic_api_key,
            "base_url": "",
        },
        "max": {
            "label": "Max",
            "provider": "anthropic",
            "model": settings.anthropic_max_model,
            "api_key": settings.anthropic_api_key,
            "base_url": "",
        },
    }


def _provider_env_defaults(provider: str) -> dict[str, str]:
    """Return env-based defaults for a specific provider (model, key, url)."""
    from app.config import settings
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


async def get_llm_providers() -> dict[str, dict[str, str]]:
    """Return LLM provider config for all tiers.

    Merges .env defaults with any JSON overrides.
    When a provider is switched, auto-fills model/key/url from that
    provider's env defaults (unless explicitly overridden).
    API keys are masked for display (last 6 chars visible).
    """
    defaults = _llm_defaults()
    overrides = _read_overrides()
    llm_over = overrides.get("_llm_providers", {})

    result: dict[str, dict[str, str]] = {}
    for tier, default in defaults.items():
        over = llm_over.get(tier, {})
        provider = over.get("provider", default["provider"])

        # If provider was switched, get that provider's env defaults
        if provider != default["provider"]:
            prov_env = _provider_env_defaults(provider)
            model = over.get("model", prov_env.get("model", ""))
            key = over.get("api_key", prov_env.get("api_key", ""))
            base_url = over.get("base_url", prov_env.get("base_url", ""))
        else:
            model = over.get("model", default["model"])
            key = over.get("api_key", default["api_key"])
            base_url = over.get("base_url", default["base_url"])

        result[tier] = {
            "label": default["label"],
            "provider": provider,
            "model": model,
            "api_key_masked": _mask_key(key),
            "api_key_set": bool(
                key and key not in ("", "sk-xxx", "sk-ant-xxx", "xxx"),
            ),
            "base_url": base_url,
            "has_override": bool(over),
        }
    return result


async def update_llm_provider(
    tier: str, patch: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Update a single LLM tier's config."""
    if tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier '{tier}'")

    async with _write_lock:
        overrides = _read_overrides()
        llm_section = overrides.get("_llm_providers", {})
        current = llm_section.get(tier, {})

        for key in ("model", "api_key", "base_url", "provider"):
            if key in patch and patch[key] is not None:
                val = patch[key]
                if val:
                    current[key] = val
                else:
                    current.pop(key, None)

        if current:
            llm_section[tier] = current
        else:
            llm_section.pop(tier, None)

        if llm_section:
            overrides["_llm_providers"] = llm_section
        else:
            overrides.pop("_llm_providers", None)

        _write_overrides(overrides)

    # Reload settings into the live LLM factories
    _apply_llm_overrides()

    return await get_llm_providers()


async def reset_llm_providers() -> dict[str, dict[str, str]]:
    """Reset all LLM provider configs to .env defaults."""
    async with _write_lock:
        overrides = _read_overrides()
        overrides.pop("_llm_providers", None)
        _write_overrides(overrides)
    _apply_llm_overrides()
    return await get_llm_providers()


def _mask_key(key: str) -> str:
    """Mask API key for display: show last 6 chars."""
    if not key or key in ("", "sk-xxx", "sk-ant-xxx"):
        return ""
    if len(key) <= 8:
        return "***" + key[-3:]
    return "***" + key[-6:]


def _apply_llm_overrides() -> None:
    """Clear LLM cache so provider config changes take effect.

    The provider-based factory reads overrides directly from
    agent_config.json at creation time, so we only need to bust
    the LRU cache here.
    """
    try:
        from app.llm_factory import get_llm
        get_llm.cache_clear()
    except Exception:
        pass


# ── Available models catalog ──────────────────────────────────
# Curated list of models per provider. Shown in the UI as a dropdown
# so users don't have to memorize model strings.

KNOWN_MODELS: list[dict[str, str]] = [
    # DeepSeek
    {
        "id": "deepseek-chat",
        "name": "DeepSeek V3",
        "provider": "deepseek",
        "tier": "fast",
        "context": "128K",
    },
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek R1",
        "provider": "deepseek",
        "tier": "smart",
        "context": "128K",
    },
    # OpenAI
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "openai",
        "tier": "fast",
        "context": "128K",
        "vision": True,
    },
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "tier": "smart",
        "context": "128K",
        "vision": True,
    },
    {
        "id": "gpt-4.1",
        "name": "GPT-4.1",
        "provider": "openai",
        "tier": "smart",
        "context": "1M",
        "vision": True,
    },
    {
        "id": "gpt-4.1-mini",
        "name": "GPT-4.1 Mini",
        "provider": "openai",
        "tier": "fast",
        "context": "1M",
        "vision": True,
    },
    {
        "id": "gpt-4.1-nano",
        "name": "GPT-4.1 Nano",
        "provider": "openai",
        "tier": "fast",
        "context": "1M",
        "vision": True,
    },
    {
        "id": "o3",
        "name": "O3",
        "provider": "openai",
        "tier": "max",
        "context": "200K",
    },
    {
        "id": "o3-mini",
        "name": "O3 Mini",
        "provider": "openai",
        "tier": "strong",
        "context": "200K",
    },
    {
        "id": "o4-mini",
        "name": "O4 Mini",
        "provider": "openai",
        "tier": "strong",
        "context": "200K",
    },
    # Anthropic
    {
        "id": "claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "tier": "strong",
        "context": "200K",
        "vision": True,
    },
    {
        "id": "claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "provider": "anthropic",
        "tier": "max",
        "context": "200K",
        "vision": True,
    },
    {
        "id": "claude-haiku-4-5-20251001",
        "name": "Claude Haiku 4.5",
        "provider": "anthropic",
        "tier": "fast",
        "context": "200K",
        "vision": True,
    },
    # GLM / 智谱
    {
        "id": "glm-4-flash",
        "name": "GLM-4 Flash",
        "provider": "glm",
        "tier": "fast",
        "context": "128K",
    },
    {
        "id": "glm-4-plus",
        "name": "GLM-4 Plus",
        "provider": "glm",
        "tier": "smart",
        "context": "128K",
    },
    {
        "id": "glm-4",
        "name": "GLM-4",
        "provider": "glm",
        "tier": "smart",
        "context": "128K",
    },
    # Qwen / 通义千问
    {
        "id": "qwen-turbo",
        "name": "Qwen Turbo",
        "provider": "qwen",
        "tier": "fast",
        "context": "128K",
    },
    {
        "id": "qwen-plus",
        "name": "Qwen Plus",
        "provider": "qwen",
        "tier": "smart",
        "context": "128K",
    },
    {
        "id": "qwen-max",
        "name": "Qwen Max",
        "provider": "qwen",
        "tier": "strong",
        "context": "32K",
    },
    # Qwen VL — vision-capable. pagegen / planner need these for
    # reference-image flows; selecting a non-VL Qwen there silently
    # strips images and produces blind output (see PR #1 follow-up).
    {
        "id": "qwen-vl-plus",
        "name": "Qwen VL Plus（视觉）",
        "provider": "qwen",
        "tier": "smart",
        "context": "32K",
        "vision": True,
    },
    {
        "id": "qwen-vl-max",
        "name": "Qwen VL Max（视觉）",
        "provider": "qwen",
        "tier": "strong",
        "context": "32K",
        "vision": True,
    },
    {
        "id": "qwen2.5-vl-72b-instruct",
        "name": "Qwen2.5 VL 72B（视觉）",
        "provider": "qwen",
        "tier": "max",
        "context": "128K",
        "vision": True,
    },
]


def get_available_models() -> dict[str, list[dict[str, str]]]:
    """Return known models grouped by provider.

    Result format::

        {
          "deepseek": [{"id": "deepseek-chat", "name": "DeepSeek V3", ...}],
          "openai":   [...],
          "anthropic": [...],
          "all": [...],   # flat list
        }
    """
    by_provider: dict[str, list[dict[str, str]]] = {}
    for m in KNOWN_MODELS:
        by_provider.setdefault(m["provider"], []).append(m)
    by_provider["all"] = KNOWN_MODELS
    return by_provider


# ── Helpers for plugins to read their current config ────────────

def get_effective_prompt(plugin_name: str) -> str:
    """Sync helper: return the effective system prompt for a plugin."""
    default = _DEFAULTS.get(plugin_name, {})
    overrides = _read_overrides()
    over = overrides.get(plugin_name, {})
    return over.get("system_prompt", default.get("system_prompt", ""))


def get_effective_tier(plugin_name: str) -> str:
    """Sync helper: return the effective model tier for a plugin."""
    default = _DEFAULTS.get(plugin_name, {})
    overrides = _read_overrides()
    over = overrides.get(plugin_name, {})
    return over.get("model_tier", default.get("model_tier", "smart"))


def get_effective_gen_tier(plugin_name: str) -> str:
    """Sync helper: return the effective generation model tier."""
    default = _DEFAULTS.get(plugin_name, {})
    overrides = _read_overrides()
    over = overrides.get(plugin_name, {})
    return over.get(
        "gen_model_tier",
        default.get("gen_model_tier", ""),
    )
