import os
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Set test DB before app imports build engine
os.environ["TEST_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/99"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["LLM_ENABLED"] = "false"
# Observability must be inert in tests: empty endpoint disables tracing and
# background prefetch is exercised directly by the cache tests.
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
os.environ["PREFETCH_ENABLED"] = "false"

from app.config import get_settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app, _seed_scales  # noqa: E402
from app.models import Base, Class, User, UserRole  # noqa: E402
from app.security import hash_password  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session", autouse=True)
def override_settings():
    get_settings.cache_clear()
    settings = get_settings()
    settings.database_url = "sqlite+aiosqlite:///:memory:"
    settings.testing = True
    settings.llm_enabled = False
    yield settings
    get_settings.cache_clear()


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def client(db) -> AsyncGenerator[AsyncClient, None]:
    async def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db
    await _seed_scales(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def create_user(
    db: AsyncSession,
    role: UserRole,
    username: str,
    real_name: str = "Test",
    password: str = "Test1234!",
    class_id: int | None = None,
    phone: str | None = None,
    must_change: bool = False,
    is_homeroom: bool = False,
) -> User:
    user = User(
        role=role,
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        gender="男",
        phone=phone,
        class_id=class_id,
        is_homeroom=is_homeroom,
        must_change_password=must_change,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_class(db: AsyncSession, name: str = "七年级(1)班", head_teacher_id: int | None = None):
    from app.models import GradeLevel
    cls = Class(name=name, grade_level=GradeLevel.JUNIOR, head_teacher_id=head_teacher_id)
    db.add(cls)
    await db.commit()
    await db.refresh(cls)
    return cls


async def auth_token(client: AsyncClient, username: str, password: str = "Test1234!") -> str:
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
