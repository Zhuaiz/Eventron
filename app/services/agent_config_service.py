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
    """Return current .env-based LLM provider defaults."""
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


async def get_llm_providers() -> dict[str, dict[str, str]]:
    """Return LLM provider config for all tiers.

    Merges .env defaults with any JSON overrides.
    API keys are masked for display (last 6 chars visible).
    """
    defaults = _llm_defaults()
    overrides = _read_overrides()
    llm_over = overrides.get("_llm_providers", {})

    result: dict[str, dict[str, str]] = {}
    for tier, default in defaults.items():
        over = llm_over.get(tier, {})
        key = over.get("api_key", default["api_key"])
        result[tier] = {
            "label": default["label"],
            "provider": over.get("provider", default["provider"]),
            "model": over.get("model", default["model"]),
            "api_key_masked": _mask_key(key),
            "api_key_set": bool(key and key not in ("", "sk-xxx", "sk-ant-xxx")),
            "base_url": over.get("base_url", default["base_url"]),
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
    """Apply LLM JSON overrides to the live settings singleton.

    This lets runtime changes take effect without restart.
    """
    from app.config import settings

    overrides = _read_overrides()
    llm_over = overrides.get("_llm_providers", {})

    for tier, vals in llm_over.items():
        if tier == "fast":
            if "model" in vals:
                settings.deepseek_model = vals["model"]
            if "api_key" in vals:
                settings.deepseek_api_key = vals["api_key"]
            if "base_url" in vals:
                settings.deepseek_base_url = vals["base_url"]
        elif tier == "smart":
            if "model" in vals:
                settings.openai_model = vals["model"]
            if "api_key" in vals:
                settings.openai_api_key = vals["api_key"]
        elif tier == "strong":
            if "model" in vals:
                settings.anthropic_model = vals["model"]
            if "api_key" in vals:
                settings.anthropic_api_key = vals["api_key"]
        elif tier == "max":
            if "model" in vals:
                settings.anthropic_max_model = vals["model"]
            # Max shares api_key with strong (anthropic)
            if "api_key" in vals:
                settings.anthropic_api_key = vals["api_key"]

    # Clear LRU caches so new settings take effect
    try:
        from app.llm_factory import get_llm
        get_llm.cache_clear()
    except Exception:
        pass


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
