"""Pre-fetch cache for the next adaptive item.

After a successful ``/answer`` (or right after ``/start``) we asynchronously
compute the next item and stash it so that the following ``GET /next`` can
return in <20ms instead of paying a synchronous LLM round-trip.

Primary store is Redis (key ``compassio:next:{assessment_id}``, TTL 300s).
When Redis is unavailable we transparently fall back to a bounded in-process
dict cache (capacity 500, TTL 300s).  Cache failures must never surface to the
caller.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import db_session, get_redis
from app.engine.adaptive import pick_next_item
from app.llm.service import resolve_provider
from app.models import Assessment, AssessmentStatus, ScaleDef
from app.observability.metrics import inc_next_cache
from app.observability.tracing import set_span_attributes, start_span

logger = logging.getLogger("compassio.next_cache")

KEY_PREFIX = "compassio:next:"
TTL_SECONDS = 300
LOCAL_MAX_ITEMS = 500

# key -> (expiry_monotonic, payload)
_local_cache: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()

# Strong references to in-flight prefetch tasks so they aren't GC'd mid-flight.
_background_tasks: set[asyncio.Task] = set()


def cache_key(assessment_id: int) -> str:
    return f"{KEY_PREFIX}{assessment_id}"


def clear_local_cache() -> None:
    _local_cache.clear()


def _local_set(key: str, payload: dict[str, Any]) -> None:
    _local_cache[key] = (time.monotonic() + TTL_SECONDS, payload)
    _local_cache.move_to_end(key)
    while len(_local_cache) > LOCAL_MAX_ITEMS:
        _local_cache.popitem(last=False)


def _local_pop(key: str) -> dict[str, Any] | None:
    entry = _local_cache.pop(key, None)
    if entry is None:
        return None
    expires_at, payload = entry
    if expires_at < time.monotonic():
        return None
    return payload


async def write_next(assessment_id: int, payload: dict[str, Any]) -> str:
    """Store ``payload`` for ``assessment_id``; returns the backend used."""
    key = cache_key(assessment_id)
    body = json.dumps(payload, ensure_ascii=False)

    client = get_redis()
    if client is not None:
        try:
            await client.set(key, body, ex=TTL_SECONDS)
            inc_next_cache("prefetch_written")
            return "redis"
        except Exception:
            logger.warning("next-cache redis write failed; using local fallback")

    _local_set(key, payload)
    inc_next_cache("prefetch_written")
    return "local"


async def read_next(assessment_id: int) -> dict[str, Any] | None:
    """Read *and consume* the cached next item (one-shot)."""
    key = cache_key(assessment_id)

    client = get_redis()
    if client is not None:
        try:
            raw = await client.get(key)
            if raw:
                await client.delete(key)
                inc_next_cache("hit")
                return json.loads(raw)
        except Exception:
            logger.warning("next-cache redis read failed; using local fallback")

    payload = _local_pop(key)
    if payload is not None:
        inc_next_cache("hit")
        return payload

    # Miss accounting is classified by the caller (`/next`), which knows whether
    # the fallback actually blocked on the LLM (reason=llm_blocked) or was served
    # deterministically by the rules (reason=no_prefetch). Emitting it here would
    # lose that distinction, so we deliberately do not count it.
    return None


async def _compute_next(session, assessment_id: int) -> tuple[dict[str, Any] | None, str]:
    result = await session.execute(
        select(Assessment)
        .where(Assessment.id == assessment_id)
        .options(selectinload(Assessment.responses))
    )
    assessment = result.scalar_one_or_none()
    if assessment is None or assessment.status == AssessmentStatus.COMPLETED:
        return None, "skip"

    scale = (
        await session.execute(select(ScaleDef).where(ScaleDef.scale_id == assessment.scale_id))
    ).scalar_one_or_none()
    if scale is None:
        return None, "skip"

    answered = {r.item_id: r.value for r in assessment.responses}
    provider = await resolve_provider(session)

    span = start_span("next.prefetch", {"scale": assessment.scale_id})
    with span as active:
        item_id, transition, fallback, source = await pick_next_item(
            scale.payload, answered, provider, assessment_id=assessment_id
        )
        set_span_attributes(
            active,
            {"scale": assessment.scale_id, "stage": "prefetch", "outcome": source},
        )

    payload = {
        "item_id": item_id,
        "transition": transition,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return payload, source


async def prefetch_next(assessment_id: int, session=None) -> None:
    """Compute and cache the next item.  Swallows *all* errors."""
    try:
        if session is not None:
            payload, _ = await _compute_next(session, assessment_id)
            if payload is not None:
                await write_next(assessment_id, payload)
            return
        async with db_session() as own_session:
            payload, _ = await _compute_next(own_session, assessment_id)
        if payload is not None:
            await write_next(assessment_id, payload)
    except asyncio.CancelledError:  # pragma: no cover - cooperative cancel
        raise
    except Exception:
        inc_next_cache("prefetch_error")
        logger.warning("next prefetch failed assessment_id=%s", assessment_id, exc_info=True)


def schedule_prefetch(assessment_id: int) -> None:
    """Fire-and-forget prefetch on the running loop (never blocks the request)."""
    try:
        from app.config import get_settings

        if not get_settings().prefetch_enabled:
            return
    except Exception:  # pragma: no cover
        pass
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        task = loop.create_task(prefetch_next(assessment_id))
    except Exception:  # pragma: no cover
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


__all__ = [
    "KEY_PREFIX",
    "TTL_SECONDS",
    "LOCAL_MAX_ITEMS",
    "cache_key",
    "clear_local_cache",
    "write_next",
    "read_next",
    "prefetch_next",
    "schedule_prefetch",
]
