"""LLM model catalog — pulls model lists from each provider's /models API.

Why this exists:
    Hard-coding a static ``KNOWN_MODELS`` list goes stale every time a
    provider ships a new SKU (Qwen VL Max was the example that surfaced this).
    Instead, fan out to each provider's list-models endpoint at request time,
    merge with a small overlay for display polish, cache for 1 hour.

    Vision capability is NOT returned by any provider's /models endpoint, so
    it is inferred from the model ID via regex patterns. Conservative — we
    only mark ``vision=True`` when confident.

Cache strategy:
    In-process dict + asyncio.Lock + 1h TTL. ``refresh=True`` bypasses TTL.
    On provider-side failure (no key, network down, 4xx), we fall back to
    the overlay-derived entries for that provider so the UI never goes
    completely empty.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ── Vision-capability inference ───────────────────────────────
# Provider /models responses do not include a "vision" flag, so we infer
# it from the model ID. Patterns are conservative; unknown IDs default to
# vision=False (failing closed protects the harness from silently sending
# images to text-only models).

_VISION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"vl[-_]"),                                       # qwen-vl-*
    re.compile(r"vision", re.IGNORECASE),
    re.compile(r"gpt-4o"),
    re.compile(r"gpt-4\.1"),                                     # 4.1 family is multimodal
    re.compile(r"^o[1-9]"),                                      # o1 / o3 / o4 reasoning
    re.compile(r"claude-(opus|sonnet|haiku)-(3-5|3\.5|4|5)"),
    re.compile(r"gemini"),
    re.compile(r"glm-4v"),
]


def _infer_vision(model_id: str) -> bool:
    return any(p.search(model_id) for p in _VISION_PATTERNS)


# ── Display-name overlay ──────────────────────────────────────
# The provider APIs return raw IDs (Anthropic also returns ``display_name``
# but the others don't). This map lets us render a friendly label for
# common IDs. New IDs from the API just use the raw ID — that's fine,
# users can always read the ID directly.

_DISPLAY_OVERLAY: dict[str, str] = {
    "deepseek-chat":              "DeepSeek V3",
    "deepseek-reasoner":          "DeepSeek R1",
    "qwen-turbo":                 "Qwen Turbo",
    "qwen-plus":                  "Qwen Plus",
    "qwen-max":                   "Qwen Max",
    "qwen-vl-plus":               "Qwen VL Plus（视觉）",
    "qwen-vl-max":                "Qwen VL Max（视觉）",
    "qwen2.5-vl-72b-instruct":    "Qwen2.5 VL 72B（视觉）",
    "qwen2-vl-72b-instruct":      "Qwen2 VL 72B（视觉）",
    "qwen2-vl-7b-instruct":       "Qwen2 VL 7B（视觉）",
    "glm-4-flash":                "GLM-4 Flash",
    "glm-4-plus":                 "GLM-4 Plus",
    "glm-4":                      "GLM-4",
    "glm-4v":                     "GLM-4V（视觉）",
    "glm-4v-plus":                "GLM-4V Plus（视觉）",
    "gpt-4o":                     "GPT-4o",
    "gpt-4o-mini":                "GPT-4o Mini",
    "gpt-4.1":                    "GPT-4.1",
    "gpt-4.1-mini":               "GPT-4.1 Mini",
    "gpt-4.1-nano":               "GPT-4.1 Nano",
}


# ── OpenAI list filtering ─────────────────────────────────────
# OpenAI /v1/models returns 100+ entries: embeddings, TTS/whisper, image,
# realtime, moderation, fine-tunes, legacy completions. We need only the
# chat-completion models for our picker.

_OPENAI_DROP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"embed"),
    re.compile(r"tts|whisper|transcribe", re.IGNORECASE),
    re.compile(r"^dall-e"),
    re.compile(r"^gpt-image"),
    re.compile(r"realtime"),
    re.compile(r"moderation"),
    re.compile(r"^(babbage|curie|ada|davinci-002)"),             # legacy completions
    re.compile(r":ft:"),                                         # fine-tunes
    re.compile(r"audio-preview"),
    re.compile(r"computer-use"),
    re.compile(r"-search-"),
]

_OPENAI_KEEP_PREFIX = re.compile(r"^(gpt-|o[1-9]|chatgpt-)")


def _is_openai_chat_model(model_id: str) -> bool:
    if any(p.search(model_id) for p in _OPENAI_DROP_PATTERNS):
        return False
    return bool(_OPENAI_KEEP_PREFIX.match(model_id))


# ── Provider routing ──────────────────────────────────────────

_PROVIDER_BASE_URLS: dict[str, str] = {
    "openai":    "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek":  "https://api.deepseek.com/v1",
    "glm":       "https://open.bigmodel.cn/api/paas/v4",
    "qwen":      "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


def _id_to_provider(model_id: str) -> str:
    """Best-effort mapping from raw ID to provider. Used for fallback only."""
    if model_id.startswith("claude-"):
        return "anthropic"
    if model_id.startswith(("gpt-", "chatgpt-")) or re.match(r"^o[1-9]", model_id):
        return "openai"
    if model_id.startswith("deepseek-"):
        return "deepseek"
    if model_id.startswith("glm-"):
        return "glm"
    if model_id.startswith("qwen"):
        return "qwen"
    return "unknown"


def _provider_credentials(provider: str) -> dict[str, str] | None:
    """Resolve api_key + base_url for a provider from env settings.

    Returns ``None`` if no usable key is configured. Mirrors the placeholder
    detection used elsewhere in the codebase.
    """
    table: dict[str, tuple[str, str]] = {
        "openai": (
            settings.openai_api_key, _PROVIDER_BASE_URLS["openai"],
        ),
        "anthropic": (
            settings.anthropic_api_key, _PROVIDER_BASE_URLS["anthropic"],
        ),
        "deepseek": (
            settings.deepseek_api_key,
            settings.deepseek_base_url or _PROVIDER_BASE_URLS["deepseek"],
        ),
        "glm": (
            settings.glm_api_key,
            settings.glm_base_url or _PROVIDER_BASE_URLS["glm"],
        ),
        "qwen": (
            settings.qwen_api_key,
            settings.qwen_base_url or _PROVIDER_BASE_URLS["qwen"],
        ),
    }
    info = table.get(provider)
    if not info:
        return None
    api_key, base_url = info
    if not api_key or api_key in ("sk-xxx", "sk-ant-xxx", "xxx", ""):
        return None
    return {"api_key": api_key, "base_url": base_url}


# ── Per-provider fetchers ─────────────────────────────────────

def _normalize_entry(
    model_id: str, provider: str,
    api_display: str | None = None,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": _DISPLAY_OVERLAY.get(model_id) or api_display or model_id,
        "provider": provider,
        "context": "",                                           # not provided by APIs
        "vision": _infer_vision(model_id),
    }


async def _fetch_openai_compat(
    provider: str, base_url: str, api_key: str,
) -> list[dict[str, Any]]:
    """Fetch from any OpenAI-compatible /models endpoint.

    Used for OpenAI, DeepSeek, GLM (paas/v4 is OpenAI-compat), Qwen DashScope
    compat mode. All accept ``Authorization: Bearer <key>`` and return
    ``{"data": [{"id": ...}, ...]}``.
    """
    url = f"{base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        r.raise_for_status()
        body = r.json()

    raw = body.get("data") or []
    out: list[dict[str, Any]] = []
    for m in raw:
        mid = m.get("id") or ""
        if not mid:
            continue
        if provider == "openai" and not _is_openai_chat_model(mid):
            continue
        out.append(_normalize_entry(mid, provider))
    return out


async def _fetch_anthropic(api_key: str) -> list[dict[str, Any]]:
    """Anthropic native /v1/models. Different auth header + version pin."""
    url = f"{_PROVIDER_BASE_URLS['anthropic']}/models"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        r.raise_for_status()
        body = r.json()

    raw = body.get("data") or []
    out: list[dict[str, Any]] = []
    for m in raw:
        mid = m.get("id") or ""
        if not mid:
            continue
        out.append(_normalize_entry(
            mid, "anthropic", api_display=m.get("display_name"),
        ))
    return out


async def _fetch_one(provider: str) -> list[dict[str, Any]]:
    """Fetch model list for one provider. Failures degrade to empty list.

    Empty doesn't mean "provider has no models" — it means "we couldn't
    reach it right now". The caller layers in overlay-derived fallbacks
    so the picker never goes completely empty.
    """
    creds = _provider_credentials(provider)
    if not creds:
        return []
    try:
        if provider == "anthropic":
            return await _fetch_anthropic(creds["api_key"])
        return await _fetch_openai_compat(
            provider, creds["base_url"], creds["api_key"],
        )
    except Exception as e:                                       # noqa: BLE001
        logger.warning(
            "model_catalog: fetch failed for %s: %s: %s",
            provider, type(e).__name__, e,
        )
        return []


# ── Cache ─────────────────────────────────────────────────────

_CACHE_TTL = 3600.0                                              # 1 hour
_cache: dict[str, list[dict[str, Any]]] = {}
_cache_at: float = 0.0
_cache_lock = asyncio.Lock()


def _overlay_fallback(provider: str | None = None) -> list[dict[str, Any]]:
    """Build entries from the static overlay only.

    Used when a provider fetch returned [] (no key, network failure) so the
    picker still has *something* to show. If ``provider`` is given, only
    return that provider's entries.
    """
    out: list[dict[str, Any]] = []
    for mid, _name in _DISPLAY_OVERLAY.items():
        prov = _id_to_provider(mid)
        if provider is not None and prov != provider:
            continue
        if prov == "unknown":
            continue
        out.append(_normalize_entry(mid, prov))
    return out


async def get_catalog(
    refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Return the full model catalog grouped by provider.

    Args:
        refresh: bypass the TTL cache and refetch from every provider.

    Returns:
        ``{
            "openai":    [...],
            "anthropic": [...],
            "deepseek":  [...],
            "glm":       [...],
            "qwen":      [...],
            "all":       [...],   # flat
        }`` — providers with no models (no key, fetch failed, no fallback)
        are simply omitted from the dict.
    """
    global _cache_at, _cache

    now = time.monotonic()
    async with _cache_lock:
        if not refresh and _cache and now - _cache_at < _CACHE_TTL:
            cached = dict(_cache)
        else:
            providers = list(_PROVIDER_BASE_URLS.keys())
            results = await asyncio.gather(*[
                _fetch_one(p) for p in providers
            ])
            new_cache: dict[str, list[dict[str, Any]]] = {}
            for prov, models in zip(providers, results):
                if models:
                    new_cache[prov] = models
                else:
                    # Fetch failed or no key — fall back to overlay so the
                    # picker still has *something* for that provider.
                    fallback = _overlay_fallback(prov)
                    if fallback:
                        new_cache[prov] = fallback
            _cache = new_cache
            _cache_at = now
            cached = dict(_cache)

    flat = [m for ms in cached.values() for m in ms]
    return {**cached, "all": flat}


def cache_info() -> dict[str, Any]:
    """Diagnostic: who's in the cache and how stale is it."""
    age = (
        time.monotonic() - _cache_at if _cache_at else None
    )
    return {
        "providers": {p: len(ms) for p, ms in _cache.items()},
        "age_seconds": round(age, 1) if age is not None else None,
        "ttl_seconds": _CACHE_TTL,
    }
