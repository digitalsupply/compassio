"""LLM checkpoint scheduler for the ``fusion`` adaptive strategy.

Under ``fusion`` the deterministic rules pick *every* item; the LLM is only
consulted at sparse checkpoints, spaced
``[ADAPTIVE_LLM_INTERVAL_MIN, ADAPTIVE_LLM_INTERVAL_MAX]`` answered items apart.
That turns ~1 call/item (≈84 calls for a 100-item MHT) into ~6 checks.

State is one integer per assessment — the answered-count at which the next
checkpoint is due.  It lives in Redis under ``compassio:llm_sched:{id}`` with a
2h TTL.  When Redis is unavailable we transparently fall back to a bounded
in-process dict (capacity 500), mirroring ``app/next_cache.py``.

The interval is drawn from ``random.Random(f"{assessment_id}:{answered_count}")``
so a given assessment replays deterministically and no global RNG state is
touched.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections import OrderedDict

from app.config import get_settings
from app.db import get_redis

logger = logging.getLogger("compassio.checkpoint")

KEY_PREFIX = "compassio:llm_sched:"
TTL_SECONDS = 2 * 60 * 60  # 2h
LOCAL_MAX_ITEMS = 500

# key -> (expiry_monotonic, json_payload)
_local_state: "OrderedDict[str, tuple[float, str]]" = OrderedDict()


def schedule_key(assessment_id: int) -> str:
    return f"{KEY_PREFIX}{assessment_id}"


def clear_local_state() -> None:
    _local_state.clear()


def _interval(assessment_id: int, answered_count: int) -> int:
    settings = get_settings()
    lo = int(settings.adaptive_llm_interval_min)
    hi = int(settings.adaptive_llm_interval_max)
    if hi < lo:
        lo, hi = hi, lo
    if hi <= 0:
        return max(1, lo)
    rng = random.Random(f"{assessment_id}:{answered_count}")
    return rng.randint(lo, hi)


def _local_set(key: str, payload: str) -> None:
    _local_state[key] = (time.monotonic() + TTL_SECONDS, payload)
    _local_state.move_to_end(key)
    while len(_local_state) > LOCAL_MAX_ITEMS:
        _local_state.popitem(last=False)


def _local_get(key: str) -> str | None:
    entry = _local_state.get(key)
    if entry is None:
        return None
    expires_at, payload = entry
    if expires_at < time.monotonic():
        _local_state.pop(key, None)
        return None
    _local_state.move_to_end(key)
    return payload


async def _load(assessment_id: int) -> int | None:
    key = schedule_key(assessment_id)
    client = get_redis()
    if client is not None:
        try:
            raw = await client.get(key)
            if raw is not None:
                data = raw if isinstance(raw, str) else raw.decode()
                return int(json.loads(data)["next"])
        except Exception:
            logger.warning("checkpoint redis read failed; using local fallback")
            # fall through to the local cache

    raw = _local_get(key)
    if raw is None:
        return None
    try:
        return int(json.loads(raw)["next"])
    except Exception:  # pragma: no cover - corrupt entry
        return None


async def _save(assessment_id: int, next_checkpoint: int) -> str:
    key = schedule_key(assessment_id)
    payload = json.dumps({"next": int(next_checkpoint)})

    client = get_redis()
    if client is not None:
        try:
            await client.set(key, payload, ex=TTL_SECONDS)
            return "redis"
        except Exception:
            logger.warning("checkpoint redis write failed; using local fallback")

    _local_set(key, payload)
    return "local"


async def should_consult_llm(assessment_id: int, answered_count: int) -> bool:
    """Advance the scheduler and report whether this call is a checkpoint.

    Missing state initialises ``next_checkpoint`` to a random interval; a
    reached checkpoint advances it by a fresh random interval and returns
    ``True``.  Repeated calls at the same ``answered_count`` are idempotent
    (the state is advanced on the first hit), so a re-issued ``/next`` or a
    prefetch cannot double-consume a checkpoint.
    """
    state = await _load(assessment_id)
    if state is None:
        await _save(assessment_id, _interval(assessment_id, answered_count))
        return False
    if answered_count >= state:
        await _save(assessment_id, state + _interval(assessment_id, answered_count))
        return True
    return False


__all__ = [
    "KEY_PREFIX",
    "TTL_SECONDS",
    "LOCAL_MAX_ITEMS",
    "schedule_key",
    "clear_local_state",
    "should_consult_llm",
]
