from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings

# JSONB on PostgreSQL, plain JSON everywhere else (sqlite tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")

# 供「需要追踪原地变更（如 list.append）的 JSON 列」使用。Mutable.as_mutable 是
# 「实例级」注册：若直接包裹上面的共享 JsonType，会把所有用它的列（payload/scores…）
# 一并变成 MutableList 并在赋 dict 时抛 TypeError。故单独建一个实例专供这类列。
JsonListType = MutableList.as_mutable(JSON().with_variant(JSONB(), "postgresql"))


def build_engine(settings: Settings):
    url = settings.database_url
    kwargs = {"future": True}
    if url.startswith("sqlite"):
        # aiosqlite needs connect_args for same-thread if using file db,
        # in-memory is fine without it.
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


engine = None


def get_engine():
    global engine
    if engine is None:
        engine = build_engine(get_settings())
    return engine


AsyncSessionLocal = None


def get_sessionmaker():
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        AsyncSessionLocal = sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            await session.close()


# Redis client (lazy)
_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(get_settings().redis_url, decode_responses=True)
        except Exception:
            return None
    return _redis_client


async def ping_redis() -> bool:
    client = get_redis()
    if client is None:
        return False
    try:
        return await client.ping()
    except Exception:
        return False
