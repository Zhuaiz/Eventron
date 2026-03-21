"""LLM factory — create LangChain chat models based on configured tiers.

Tiers:
    fast   → DeepSeek (cheapest, good for simple routing)
    smart  → OpenAI GPT-4o-mini (balanced)
    strong → Anthropic Claude Sonnet (complex reasoning)
    max    → Anthropic Claude Opus (highest capability, page gen)
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.config import settings


def _has_anthropic_key() -> bool:
    return bool(
        settings.anthropic_api_key
        and settings.anthropic_api_key != "sk-ant-xxx"
    )


def create_llm(tier: str | None = None) -> BaseChatModel:
    """Create a LangChain chat model for the given tier.

    Falls back through tiers if a provider's key is missing:
    max → strong → smart → fast.

    Args:
        tier: 'fast', 'smart', 'strong', or 'max'.
            Defaults to settings.llm_default_tier.

    Returns:
        A LangChain BaseChatModel instance.

    Raises:
        ValueError: If no LLM provider is configured.
    """
    tier = tier or settings.llm_default_tier

    # Max tier — Claude Opus, largest token budget
    if tier == "max" and _has_anthropic_key():
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=settings.anthropic_max_model,
                api_key=settings.anthropic_api_key,
                temperature=0,
                max_tokens=16384,
                timeout=120.0,
            )
        except ImportError:
            pass  # Fall through to strong

    if tier in ("max", "strong") and _has_anthropic_key():
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=settings.anthropic_model,
                api_key=settings.anthropic_api_key,
                temperature=0.3,
                max_tokens=4096,
            )
        except ImportError:
            pass  # Fall through to smart

    if tier in ("max", "strong", "smart") and settings.openai_api_key and settings.openai_api_key != "sk-xxx":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.3,
            max_tokens=4096,
        )

    if settings.deepseek_api_key and settings.deepseek_api_key != "sk-xxx":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.3,
            max_tokens=4096,
        )

    raise ValueError(
        "No LLM provider configured. Set DEEPSEEK_API_KEY, "
        "OPENAI_API_KEY, or ANTHROPIC_API_KEY in .env"
    )


@lru_cache(maxsize=4)
def get_llm(tier: str = "smart") -> BaseChatModel:
    """Cached LLM getter — reuses instances per tier."""
    return create_llm(tier)
