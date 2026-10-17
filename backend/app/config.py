import os
from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings

# JWT 签名密钥的默认值/最小长度。默认值可被公开猜到，等价于任何人都能签发
# 管理员 token，因此非测试环境启动时必须强校验（见 validate_settings）。
DEFAULT_SECRET_KEY = "change-me-in-production"
MIN_SECRET_KEY_LENGTH = 32


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

    secret_key: str = Field(default=DEFAULT_SECRET_KEY, alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=60 * 24, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    algorithm: str = "HS256"

    # 登录爆破防护：同一用户名在窗口内失败达到次数上限后拒绝登录（Redis 计数）。
    # Redis 不可用时自动放行（可用性优先，见 app/ratelimit.py）。
    login_rate_limit_attempts: int = Field(default=10, alias="LOGIN_RATE_LIMIT_ATTEMPTS")
    login_rate_limit_window_seconds: int = Field(
        default=300, alias="LOGIN_RATE_LIMIT_WINDOW_SECONDS"
    )

    # LLM env defaults (overridden by DB default config if present)
    llm_provider: str = Field(default="opencode-go", alias="LLM_PROVIDER")
    llm_base_url: str = Field(
        default="https://opencode.ai/inference/go/v1", alias="LLM_BASE_URL"
    )
    llm_api_key: Optional[str] = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="deepseek-v4.1-flash", alias="LLM_MODEL")
    llm_timeout_s: int = Field(default=30, alias="LLM_TIMEOUT_S")
    llm_enabled: bool = Field(default=True, alias="LLM_ENABLED")
    # Dependency probing (see app/main.py refresh_dependencies):
    #   the 30s loop always checks db/redis; the LLM is checked at most every
    #   llm_reachability_interval_seconds with a *token-free* probe
    #   (provider.reachable()), and the billed chat ping at most every
    #   llm_ping_interval_seconds. 0 disables that tier entirely.
    llm_reachability_interval_seconds: int = Field(
        default=900, alias="LLM_REACHABILITY_INTERVAL_SECONDS"
    )
    llm_ping_interval_seconds: int = Field(
        default=1800, alias="LLM_PING_INTERVAL_SECONDS"
    )

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


def validate_settings(settings: Settings) -> None:
    """Fail fast on a weak/default ``SECRET_KEY`` (P0 hardening).

    A guessable JWT signing key lets anyone forge admin tokens, so a
    misconfigured production deployment must refuse to start rather than run
    with a known secret. Tests (``settings.testing``) are exempt because the
    suite sets a deliberately short key.
    """
    if settings.testing:
        return
    key = (settings.secret_key or "").strip()
    if key == DEFAULT_SECRET_KEY or len(key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            "SECRET_KEY is missing or too weak: set the SECRET_KEY environment "
            f"variable to a random value of at least {MIN_SECRET_KEY_LENGTH} "
            f"characters (got {len(key)}). "
            "Example: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
