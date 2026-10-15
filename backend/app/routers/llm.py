from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.llm.presets import get_preset
from app.llm.provider import LLMProvider, ProviderConfig
from app.models import LLMConfig
from app.schemas import LLMConfigIn, LLMConfigOut
from app.security import require_admin

router = APIRouter()


async def _reset_defaults(db: AsyncSession, exclude_id: int | None = None):
    stmt = select(LLMConfig).where(LLMConfig.is_default == True)
    if exclude_id is not None:
        stmt = stmt.where(LLMConfig.id != exclude_id)
    result = await db.execute(stmt)
    for cfg in result.scalars().all():
        cfg.is_default = False


@router.get("", response_model=list[LLMConfigOut])
async def list_configs(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    result = await db.execute(select(LLMConfig))
    return result.scalars().all()


@router.post("", response_model=LLMConfigOut)
async def create_config(
    data: LLMConfigIn,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    if data.is_default:
        await _reset_defaults(db)
    cfg = LLMConfig(**data.model_dump())
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.put("/{id}", response_model=LLMConfigOut)
async def update_config(
    id: int,
    data: LLMConfigIn,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    cfg = await db.get(LLMConfig, id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    if data.is_default:
        await _reset_defaults(db, exclude_id=id)
    for k, v in data.model_dump().items():
        setattr(cfg, k, v)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.delete("/{id}")
async def delete_config(
    id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    cfg = await db.get(LLMConfig, id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    await db.delete(cfg)
    await db.commit()
    return {"ok": True}


@router.post("/{id}/test")
async def test_config(
    id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    cfg = await db.get(LLMConfig, id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    provider = LLMProvider(
        ProviderConfig(
            provider_key=cfg.provider_key,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            model=cfg.model,
            extra_headers=cfg.extra_headers or {},
            timeout_s=cfg.timeout_s,
        )
    )
    ok = await provider.ping()
    return {"ok": ok}
