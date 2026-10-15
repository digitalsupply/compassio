import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic, perf_counter

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import JsonType, db_session, get_db, get_engine, ping_redis
from app.llm.service import resolve_provider
from app.models import Base, ScaleDef, User
from app.observability.logging import setup_logging
from app.observability.metrics import (
    CONTENT_TYPE_LATEST,
    http_request_duration_seconds,
    http_requests_total,
    inc_llm_request,
    metrics_payload,
    observe_llm,
    set_dependency_up,
    users_total,
)
from app.observability.tracing import (
    set_current_span_attributes,
    set_span_attributes,
    setup_tracing,
    start_span,
)
from app.routers import (
    admin,
    assess,
    auth,
    import_,
    llm,
    notify,
    report,
    scales,
    teacher,
    users,
)
from app.schemas import HealthOut

logger = logging.getLogger("compassio.access")
_dep_logger = logging.getLogger("compassio.dependencies")

DEPENDENCY_REFRESH_SECONDS = 30
_ALL_ROLES = ("school_admin", "teacher", "student")


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
    await conn.execute(
        text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "initial_password VARCHAR(64)"
        )
    )


async def _refresh_user_metrics(db: AsyncSession) -> None:
    """Keep ``compassio_users_total{role}`` in sync (best-effort collector)."""
    try:
        rows = (await db.execute(select(User.role, func.count()).group_by(User.role))).all()
        seen = set()
        for role, count in rows:
            role_value = role.value if hasattr(role, "value") else str(role)
            users_total.labels(role_value).set(count)
            seen.add(role_value)
        for role_value in _ALL_ROLES:
            if role_value not in seen:
                users_total.labels(role_value).set(0)
    except Exception:
        _dep_logger.warning("user metrics refresh failed", exc_info=True)


async def _probe_llm(provider) -> bool:
    """Ping the provider with a manual ``llm.ping`` span + metrics."""
    model = getattr(getattr(provider, "config", None), "model", "unknown")
    started = perf_counter()
    ok = False
    outcome = "ok"
    span = start_span("llm.ping", {"stage": "ping"})
    with span as active:
        try:
            ok = await provider.ping()
            outcome = "ok" if ok else "error"
        except Exception:
            ok = False
            outcome = "error"
        duration = perf_counter() - started
        set_span_attributes(
            active,
            {
                "stage": "ping",
                "outcome": outcome,
                "duration_ms": round(duration * 1000, 3),
            },
        )
    observe_llm("ping", model, outcome, duration)
    inc_llm_request("ping", get_settings().adaptive_strategy)
    return ok


# LLM 健康缓存：/api/health 不再每次同步 ping（推理模型单次 2-5s，会拖累探针并浪费额度）
_LLM_HEALTH: dict[str, float | bool] = {"ok": False, "ts": 0.0}
LLM_HEALTH_STALE_SECONDS = 150.0


def _set_llm_health(ok: bool) -> None:
    _LLM_HEALTH["ok"] = bool(ok)
    _LLM_HEALTH["ts"] = monotonic()


def _llm_health_cached() -> tuple[bool, bool]:
    """Return (ok, stale)."""
    ts = float(_LLM_HEALTH.get("ts") or 0.0)
    return bool(_LLM_HEALTH.get("ok")), (monotonic() - ts) > LLM_HEALTH_STALE_SECONDS


async def refresh_dependencies() -> None:
    """Refresh ``compassio_dependency_up`` gauges (called by /api/health + the
    30s background task)."""
    db_ok = False
    try:
        async with db_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
            await _refresh_user_metrics(db)
    except Exception:
        db_ok = False
    set_dependency_up("db", db_ok)

    redis_ok = await ping_redis()
    set_dependency_up("redis", redis_ok)

    llm_ok = False
    try:
        async with db_session() as db:
            provider = await resolve_provider(db)
            if provider is not None:
                llm_ok = await _probe_llm(provider)
    except Exception:
        llm_ok = False
    _set_llm_health(llm_ok)
    set_dependency_up("llm", llm_ok)


async def _dependency_refresh_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await refresh_dependencies()
        except Exception:  # pragma: no cover - defensive
            _dep_logger.warning("dependency refresh failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=DEPENDENCY_REFRESH_SECONDS)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_light_migrations(conn)

    async with asynccontextmanager(get_db)() as db:
        await _seed_scales(db)
        await _refresh_user_metrics(db)

    # Observability must never be an availability dependency.
    setup_tracing(app)
    try:
        await refresh_dependencies()
    except Exception:
        pass

    stop_event = asyncio.Event()
    refresh_task = asyncio.create_task(_dependency_refresh_loop(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        refresh_task.cancel()
        try:
            await refresh_task
        except (asyncio.CancelledError, Exception):
            pass
        await engine.dispose()


app = FastAPI(title="Compassio", lifespan=lifespan)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(import_.router, prefix="/api/import", tags=["import"])
app.include_router(users.router, prefix="/api/admin", tags=["users"])
app.include_router(assess.router, prefix="/api/assess", tags=["assess"])
app.include_router(notify.router, prefix="/api/notify", tags=["notify"])
app.include_router(report.router, prefix="/api/admin/reports", tags=["reports"])
app.include_router(teacher.router, prefix="/api/teacher", tags=["teacher"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(llm.router, prefix="/api/admin/llm-configs", tags=["llm"])
app.include_router(scales.router, prefix="/api/admin/scales", tags=["scales"])


def _iter_route_templates(routes, prefix: str = ""):
    """Flatten (possibly nested) router routes into full path templates.

    FastAPI keeps routes included via ``include_router`` relative to the
    router's own prefix, so ``route.path`` alone can be ``/{id}/next``.
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            ctx = getattr(route, "include_context", None)
            sub_prefix = getattr(ctx, "prefix", "") or ""
            yield from _iter_route_templates(getattr(original, "routes", []), prefix + sub_prefix)
            continue
        path = getattr(route, "path", None)
        if path:
            yield prefix + path


_route_index_cache: dict[int, list[tuple["re.Pattern[str]", str]]] = {}


def _route_index(app) -> list[tuple["re.Pattern[str]", str]]:
    key = id(app)
    index = _route_index_cache.get(key)
    if index is None:
        index = []
        for template in _iter_route_templates(app.router.routes):
            pattern = re.sub(r"\{[^}/]+\}", "[^/]+", template)
            try:
                index.append((re.compile("^" + pattern + "$"), template))
            except re.error:  # pragma: no cover
                continue
        _route_index_cache[key] = index
    return index


def _route_template(request: Request) -> str:
    """Route *template* (concrete ids stripped) to avoid metric cardinality
    blow-up, e.g. ``/api/assess/{id}/next``."""
    concrete = request.url.path
    for regex, template in _route_index(request.app):
        if regex.match(concrete):
            return template
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"


def _record_http(request: Request, route: str, status_code: int, duration_s: float) -> None:
    method = request.method
    status_label = str(status_code)
    try:
        http_request_duration_seconds.labels(method, route, status_label).observe(duration_s)
        http_requests_total.labels(method, route, status_label).inc()
    except Exception:  # pragma: no cover
        pass
    logger.info(
        "http_request",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "route": route,
            "method": method,
            "status": status_code,
            "duration_ms": round(duration_s * 1000, 3),
        },
    )


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    set_current_span_attributes({"http.request_id": request_id})
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        _record_http(request, _route_template(request), 500, time.perf_counter() - started)
        raise
    duration = time.perf_counter() - started
    _record_http(request, _route_template(request), response.status_code, duration)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/metrics", include_in_schema=False)
async def get_metrics():
    """Prometheus scrape endpoint (no auth, no /api prefix)."""
    return Response(content=metrics_payload(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/health/live", include_in_schema=False)
async def health_live():
    """零依赖存活探针：只证明进程在跑（供 k8s livenessProbe 使用）。"""
    return {"status": "ok"}


@app.get("/api/health", response_model=HealthOut)
async def health(db: AsyncSession = Depends(get_db)):
    """就绪探针：db/redis 实时检查；LLM 走缓存（超时未刷新才真 ping 一次）。"""
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
        await _refresh_user_metrics(db)
    except Exception:
        pass
    set_dependency_up("db", db_ok)

    redis_ok = await ping_redis()
    set_dependency_up("redis", redis_ok)

    llm_ok, stale = _llm_health_cached()
    if stale:
        try:
            provider = await resolve_provider(db)
            if provider is not None:
                llm_ok = await _probe_llm(provider)
        except Exception:
            llm_ok = False
        _set_llm_health(llm_ok)
    set_dependency_up("llm", llm_ok)

    return HealthOut(db=db_ok, redis=redis_ok, llm=llm_ok)
