import os
from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Compassio Backend"
    debug: bool = Field(default=False, alias="DEBUG")

    database_url: str = Field(
        default="postgresql+asyncpg://compassio:compassio@localhost:5432/compassio",
        alias="DATABASE_URL",
    )
    test_database_url: str = Field(
        default="sqlite+aiosqlite:///:memory:", alias="TEST_DATABASE_URL"
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # next-item prefetch cache (see app/next_cache.py)
    prefetch_enabled: bool = Field(default=True, alias="PREFETCH_ENABLED")
    # otel endpoint; empty string disables tracing entirely
    otel_exporter_otlp_endpoint: Optional[str] = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_name: str = Field(
        default="compassio-backend", alias="OTEL_SERVICE_NAME"
    )

    bcrypt_rounds: int = Field(default=10, alias="BCRYPT_ROUNDS")

    secret_key: str = Field(default="change-me-in-production", alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=60 * 24, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    algorithm: str = "HS256"

    # LLM env defaults (overridden by DB default config if present)
    llm_provider: str = Field(default="opencode-go", alias="LLM_PROVIDER")
    llm_base_url: str = Field(
        default="https://opencode.ai/inference/go/v1", alias="LLM_BASE_URL"
    )
    llm_api_key: Optional[str] = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="deepseek-v4.1-flash", alias="LLM_MODEL")
    llm_timeout_s: int = Field(default=30, alias="LLM_TIMEOUT_S")
    llm_enabled: bool = Field(default=True, alias="LLM_ENABLED")

    # Adaptive item selection strategy (SPEC §6.2):
    #   fusion     - rules pick every item; LLM only at sparse checkpoints
    #   adaptive   - LLM on every weighted-phase item (legacy, ~84 calls/100)
    #   rules_only - never call the LLM
    adaptive_strategy: str = Field(default="fusion", alias="ADAPTIVE_STRATEGY")
    # Gap (in answered items) between two LLM checkpoints, randomised per
    # checkpoint in [min, max].
    adaptive_llm_interval_min: int = Field(default=12, alias="ADAPTIVE_LLM_INTERVAL_MIN")
    adaptive_llm_interval_max: int = Field(default=20, alias="ADAPTIVE_LLM_INTERVAL_MAX")
    # Upper bound on how many candidate items are sent to the LLM (ids only).
    llm_pick_top_n: int = Field(default=20, alias="LLM_PICK_TOP_N")

    # Test/CI knobs
    testing: bool = Field(default=False, alias="TESTING")

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
