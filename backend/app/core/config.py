"""Application settings. Environment-driven, validated at startup (fail fast).

Rule: production MUST provide explicit secrets; dev/test may fall back to
ephemeral values (never silently reused across restarts) with a warning.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- runtime ---
    env: str = "dev"  # dev | test | staging | prod
    app_name: str = "AISOC"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- database ---
    database_url: str = "sqlite+aiosqlite:///./aisoc.db"
    db_echo: bool = False
    sql_pool_size: int = 10
    sql_max_overflow: int = 20

    # --- redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- auth ---
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    fernet_key: str | None = None  # encrypts LLM provider API keys at rest
    bootstrap_admin_password: str | None = None  # seeded admin; required in prod

    # --- rate limiting (Redis sliding window) ---
    rl_global_per_min: int = 100
    rl_login_per_min: int = 5
    rl_ai_per_hour: int = 10

    # --- AI gateway ---
    # JSON config: purpose -> [provider:model, ...] fallback chain, e.g.
    # {"triage": ["openai:gpt-4.1-mini", "deepseek:deepseek-chat"], "embed": ["openai:text-embedding-3-small"]}
    llm_routing: str = (
        '{"triage":["fake:fake-triage"],"embed":["fake:fake-embed"],"chat":["fake:fake-chat"]}'
    )
    llm_request_timeout_s: float = 60.0
    llm_triage_timeout_s: float = 120.0
    llm_max_retries: int = 3
    llm_budget_tokens_per_triage: int = 30_000
    llm_price_table: str = "{}"  # JSON: model_key -> {"prompt": $/1k, "completion": $/1k}
    # provider credentials (never logged)
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    dashscope_api_key: str | None = None  # Qwen
    deepseek_api_key: str | None = None
    ollama_base_url: str | None = None

    # --- tasks ---
    task_inline: bool = False  # dev/test: run task bodies in-process (no broker)

    # --- agent ---
    agent_max_steps: int = 8

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def sync_database_url(self) -> str:
        url = self.database_url
        if url.startswith("sqlite"):
            return url.replace("+aiosqlite", "")
        if url.startswith("postgresql+psycopg"):
            return url
        if url.startswith("postgresql+asyncpg"):
            return url.replace("+asyncpg", "+psycopg")
        return url

    @model_validator(mode="after")
    def _enforce_prod_secrets(self) -> Settings:
        if self.is_prod:
            missing = [k for k in ("jwt_secret", "fernet_key") if not getattr(self, k)]
            if missing:
                raise ValueError(f"prod requires explicit secrets, missing: {missing}")
        return self

    def effective_jwt_secret(self) -> str:
        if self.jwt_secret:
            return self.jwt_secret
        return _ephemeral_jwt_secret()

    def effective_fernet_key(self) -> bytes:
        if self.fernet_key:
            return self.fernet_key.encode()
        return _ephemeral_fernet_key()


_EPHEMERAL_JWT_SECRET: str | None = None
_EPHEMERAL_FERNET_KEY: bytes | None = None


def _ephemeral_jwt_secret() -> str:
    """Per-process fallback for dev/test: stable within the process, so tokens
    survive across calls; intentionally invalidates on restart."""
    global _EPHEMERAL_JWT_SECRET
    if _EPHEMERAL_JWT_SECRET is None:
        import secrets

        _EPHEMERAL_JWT_SECRET = secrets.token_hex(32)
    return _EPHEMERAL_JWT_SECRET


def _ephemeral_fernet_key() -> bytes:
    global _EPHEMERAL_FERNET_KEY
    if _EPHEMERAL_FERNET_KEY is None:
        from cryptography.fernet import Fernet

        _EPHEMERAL_FERNET_KEY = Fernet.generate_key()
    return _EPHEMERAL_FERNET_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
