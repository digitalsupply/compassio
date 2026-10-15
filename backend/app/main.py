import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import JsonType, get_db, get_engine, ping_redis
from app.llm.service import resolve_provider
from app.models import Base, ScaleDef
from app.routers import admin, assess, auth, import_, llm, notify, report, scales, users
from app.schemas import HealthOut


def _load_scale_payloads() -> list[dict]:
    data_dir = Path(__file__).parent / "scales" / "data"
    payloads = []
    for name in ["mht.json", "mssmhs.json", "teacher_ref.json"]:
        path = data_dir / name
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                payloads.append(json.load(f))
    return payloads


async def _seed_scales(db: AsyncSession) -> None:
    for payload in _load_scale_payloads():
        scale_id = payload["id"]
        existing = await db.execute(select(ScaleDef).where(ScaleDef.scale_id == scale_id))
        if existing.scalar_one_or_none() is None:
            db.add(
                ScaleDef(
                    scale_id=scale_id,
                    version=payload.get("version", "1.0"),
                    payload=payload,
                )
            )
    await db.commit()


async def _apply_light_migrations(conn) -> None:
    """create_all 只建新表，不会给既有表补列；这里做幂等的轻量迁移。"""
    if conn.dialect.name != "postgresql":
        return
    await conn.execute(
        text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "is_homeroom BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_light_migrations(conn)

    async with asynccontextmanager(get_db)() as db:
        await _seed_scales(db)

    yield

    await engine.dispose()


app = FastAPI(title="Compassio", lifespan=lifespan)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(import_.router, prefix="/api/import", tags=["import"])
app.include_router(users.router, prefix="/api/admin", tags=["users"])
app.include_router(assess.router, prefix="/api/assess", tags=["assess"])
app.include_router(notify.router, prefix="/api/notify", tags=["notify"])
app.include_router(report.router, prefix="/api/admin/reports", tags=["reports"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(llm.router, prefix="/api/admin/llm-configs", tags=["llm"])
app.include_router(scales.router, prefix="/api/admin/scales", tags=["scales"])


@app.get("/api/health", response_model=HealthOut)
async def health(db: AsyncSession = Depends(get_db)):
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    redis_ok = await ping_redis()

    llm_ok = False
    try:
        provider = await resolve_provider(db)
        if provider is not None:
            llm_ok = await provider.ping()
    except Exception:
        llm_ok = False

    return HealthOut(db=db_ok, redis=redis_ok, llm=llm_ok)
