"""PostgreSQL 集成测试（P0）：覆盖 SQLite 测不到的 Postgres 专有路径。

生产跑 PostgreSQL，而默认测试套件是纯 SQLite in-memory，于是 JSONB、ILIKE、
以及启动时的 ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` 轻量迁移在生产才生效，
测试覆盖不到（详见 docs/17）。本模块在提供 ``TEST_POSTGRES_URL`` 时运行，否则整体跳过：

    TEST_POSTGRES_URL=postgresql+asyncpg://compassio:compassio@localhost:5432/compassio_test \\
        pytest tests/test_postgres.py

注意：会重置该库的 ``public`` schema（drop 后重建），请务必指向一次性测试库。
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import _apply_light_migrations, _seed_scales
from app.main import app
from app.models import (
    Assessment,
    AssessmentStatus,
    Base,
    Notification,
    ScaleDef,
    User,
    UserRole,
)
from app.routers.assess import _maybe_create_notification
from tests.conftest import create_user

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

# pytest.ini 把异步 fixture 的 loop 设为 session（asyncio_default_fixture_loop_scope=session），
# 而 asyncpg 的连接与创建它的 event loop 绑定、不能跨 loop 复用（SQLite 无此限制）。
# 因此本模块的 fixture 与测试必须统一跑在 session loop 上，否则报 "attached to a different loop"。
pytestmark = [
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="set TEST_POSTGRES_URL (postgresql+asyncpg://...) to run Postgres integration tests",
    ),
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest_asyncio.fixture(loop_scope="session")
async def pg_engine():
    engine = create_async_engine(POSTGRES_URL, future=True)
    async with engine.begin() as conn:
        # 不能用 Base.metadata.drop_all：users.class_id / classes.head_teacher_id 是匿名的
        # use_alter 外键（为解开循环依赖），Postgres 的 DROP CONSTRAINT 需要约束名，会报
        # "Can't emit DROP CONSTRAINT ... it has no name"；SQLite 走重建表不受影响。
        # 直接重置 schema 更干净，也让每次运行都是全新状态。
        await _reset_schema(conn)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await _reset_schema(conn)
    await engine.dispose()


async def _reset_schema(conn) -> None:
    await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(loop_scope="session")
async def pg_session(pg_engine):
    SessionLocal = sessionmaker(
        bind=pg_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="session")
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
    """启动迁移必须能补齐历史库缺失的列/索引，且重复执行不报错。"""
    async with pg_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS is_homeroom"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS initial_password"))
        # 模拟「既有库」：建表时带出的唯一索引先删掉，验证迁移能补回来
        await conn.execute(text("DROP INDEX IF EXISTS uq_notifications_dedup"))

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
        index_exists = (
            await conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_notifications_dedup'"
                )
            )
        ).scalar()
    assert {"is_homeroom", "initial_password"} <= columns
    assert index_exists == 1


async def test_item_order_mutable_persists(pg_session):
    """docs/05 §5.1：item_order 原地 append 必须在 Postgres 上落库（MutableList）。"""
    student = User(
        role=UserRole.STUDENT,
        username="pg_order",
        password_hash="x",
        real_name="x",
        gender="男",
        is_active=True,
    )
    pg_session.add(student)
    await pg_session.commit()
    await pg_session.refresh(student)

    a = Assessment(
        user_id=student.id, scale_id="mht", status=AssessmentStatus.IN_PROGRESS
    )
    pg_session.add(a)
    await pg_session.commit()
    await pg_session.refresh(a)
    assert a.item_order == []

    a.item_order.append("q1")
    await pg_session.commit()

    persisted = (
        await pg_session.execute(
            select(Assessment.item_order).where(Assessment.id == a.id)
        )
    ).scalar_one()
    assert persisted == ["q1"]


async def test_notification_dedup_atomic(pg_session):
    """docs/05 §5.1：通知去重靠唯一索引 + ON CONFLICT DO NOTHING（原生枚举列也须可用）。"""
    student = User(
        role=UserRole.STUDENT,
        username="pg_notify",
        password_hash="x",
        real_name="x",
        gender="男",
        is_active=True,
    )
    pg_session.add(student)
    await pg_session.commit()
    await pg_session.refresh(student)

    a = Assessment(user_id=student.id, scale_id="mht")
    pg_session.add(a)
    await pg_session.commit()
    await pg_session.refresh(a)

    flag = {"severity": "critical", "message": "命中测试规则"}
    await _maybe_create_notification(pg_session, a, flag)
    await _maybe_create_notification(pg_session, a, flag)  # 同内容重复

    count = (
        await pg_session.execute(select(func.count()).select_from(Notification))
    ).scalar_one()
    assert count == 1

    row = (await pg_session.execute(select(Notification))).scalar_one()
    with pytest.raises(IntegrityError):
        await pg_session.execute(
            insert(Notification).values(
                recipient_role=row.recipient_role,
                severity=row.severity,
                title=row.title,
                body=row.body,
                ref_student_id=row.ref_student_id,
            )
        )
        await pg_session.commit()
    await pg_session.rollback()


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
