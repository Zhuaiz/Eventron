"""Application configuration via environment variables.

Uses pydantic-settings to load from .env file or environment.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — all values come from env vars or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────
    app_name: str = "Eventron"
    debug: bool = False
    base_url: str = "http://localhost:8000"

    # ── Database ─────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://eventron:eventron@localhost:5432/eventron"
    db_echo: bool = False

    # ── Redis ────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── LLM — multi-provider, per-agent selection ────────────────
    llm_default_tier: str = "smart"  # fast | smart | strong

    # DeepSeek (fast tier)
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # OpenAI (smart tier)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Anthropic (strong tier)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Anthropic Max (max tier — highest capability, e.g. page generation)
    anthropic_max_model: str = "claude-opus-4-6"

    # GLM / 智谱 (OpenAI-compatible)
    glm_api_key: str = ""
    glm_model: str = "glm-4-flash"
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"

    # Qwen / 通义千问 (DashScope OpenAI-compatible)
    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # ── WeChat Work ──────────────────────────────────────────────
    wecom_corp_id: str = ""
    wecom_bot_secret: str = ""
    wecom_bot_token: str = ""
    wecom_bot_aes_key: str = ""

    # ── Plugin feature flags ─────────────────────────────────────
    plugin_identity: bool = True
    plugin_seating: bool = True
    plugin_checkin: bool = True
    plugin_change: bool = True
    plugin_pagegen: bool = True
    plugin_badge: bool = True
    plugin_guide: bool = True

    # ── JWT ────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production-use-a-long-random-string"

    # ── Paths ────────────────────────────────────────────────────
    template_dir: Path = Path("templates")


settings = Settings()
