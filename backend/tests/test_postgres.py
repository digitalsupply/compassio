"""PostgreSQL 集成测试（P0）：覆盖 SQLite 测不到的 Postgres 专有路径。

生产跑 PostgreSQL，而默认测试套件是纯 SQLite in-memory，于是 JSONB、ILIKE、
以及启动时的 ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` 轻量迁移在生产才生效，
测试覆盖不到（详见 docs/17）。本模块在提供 ``TEST_POSTGRES_URL`` 时运行，否则整体跳过：

    TEST_POSTGRES_URL=postgresql+asyncpg://compassio:compassio@localhost:5432/compassio_test \\
        pytest tests/test_postgres.py

注意：会在该库上 drop/create 应用表，请务必指向一次性测试库。
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import _apply_light_migrations, _seed_scales
from app.main import app
from app.models import Base, ScaleDef, User, UserRole
from tests.conftest import create_user

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set TEST_POSTGRES_URL (postgresql+asyncpg://...) to run Postgres integration tests",
)


@pytest.fixture
async def pg_engine():
    engine = create_async_engine(POSTGRES_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine):
    SessionLocal = sessionmaker(
        bind=pg_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def pg_client(pg_session):
    async def _override_get_db():
        yield pg_session

    app.dependency_overrides[get_db] = _override_get_db
    await _seed_scales(pg_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_jsonb_payload_roundtrip(pg_session):
    """JsonType 在 Postgres 上必须是真正的 JSONB 并能无损往返。"""
    payload = {"id": "mht", "nested": {"a": [1, 2, 3]}, "name": "中学生心理健康"}
    pg_session.add(ScaleDef(scale_id="mht-pg", version="1.0", payload=payload))
    await pg_session.commit()

    row = (
        await pg_session.execute(select(ScaleDef).where(ScaleDef.scale_id == "mht-pg"))
    ).scalar_one()
    assert row.payload == payload

    data_type = (
        await pg_session.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'scale_defs' AND column_name = 'payload'"
            )
        )
    ).scalar_one()
    assert data_type == "jsonb"


async def test_ilike_is_case_insensitive(pg_session):
    """账号搜索依赖 ILIKE；SQLite 上该语义与 Postgres 不同，这里锁住 Postgres 行为。"""
    pg_session.add(
        User(
            role=UserRole.STUDENT,
            username="Stu_Mixed",
            password_hash="x",
            real_name="张三",
            gender="男",
            is_active=True,
        )
    )
    await pg_session.commit()

    by_username = (
        await pg_session.execute(
            select(User).where(User.username.ilike("%stu_mixed%"))
        )
    ).scalars().all()
    assert [u.username for u in by_username] == ["Stu_Mixed"]

    by_name = (
        await pg_session.execute(select(User).where(User.real_name.ilike("%张三%")))
    ).scalars().all()
    assert len(by_name) == 1


async def test_light_migrations_add_columns_idempotently(pg_engine):
    """启动迁移必须能补齐历史库缺失的列，且重复执行不报错。"""
    async with pg_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS is_homeroom"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS initial_password"))

        await _apply_light_migrations(conn)
        await _apply_light_migrations(conn)  # 幂等

        columns = set(
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users'"
                    )
                )
            ).scalars().all()
        )
    assert {"is_homeroom", "initial_password"} <= columns


async def test_admin_login_and_ilike_search_over_http(pg_client, pg_session):
    """端到端：登录 + 账号搜索命中（走真实的 ILIKE 查询路径）。"""
    await create_user(pg_session, UserRole.SCHOOL_ADMIN, "pg_admin", real_name="管理员")
    await create_user(pg_session, UserRole.STUDENT, "Stu_Mixed", real_name="张三")

    login = await pg_client.post(
        "/api/auth/login", json={"username": "pg_admin", "password": "Test1234!"}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await pg_client.get("/api/admin/accounts?q=stu_mixed", headers=headers)
    assert resp.status_code == 200, resp.text
    assert [u["username"] for u in resp.json()] == ["Stu_Mixed"]
