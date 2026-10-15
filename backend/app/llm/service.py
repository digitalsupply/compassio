from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.presets import get_preset
from app.llm.provider import LLMProvider, ProviderConfig
from app.models import LLMConfig


async def resolve_provider(db: AsyncSession | None = None) -> LLMProvider | None:
    settings = get_settings()
    if not settings.llm_enabled:
        return None

    config_row: LLMConfig | None = None
    if db is not None:
        result = await db.execute(
            select(LLMConfig).where(
                LLMConfig.is_active == True, LLMConfig.is_default == True
            )
        )
        config_row = result.scalar_one_or_none()

    if config_row is not None:
        return LLMProvider(
            ProviderConfig(
                provider_key=config_row.provider_key,
                base_url=config_row.base_url,
                api_key=config_row.api_key,
                model=config_row.model,
                extra_headers=config_row.extra_headers or {},
                timeout_s=config_row.timeout_s,
            )
        )

    preset = get_preset(settings.llm_provider)
    return LLMProvider(
        ProviderConfig(
            provider_key=settings.llm_provider,
            base_url=settings.llm_base_url or preset["base_url"],
            api_key=settings.llm_api_key,
            model=settings.llm_model or preset["model"],
            extra_headers=preset.get("extra_headers", {}),
            timeout_s=settings.llm_timeout_s,
        )
    )
