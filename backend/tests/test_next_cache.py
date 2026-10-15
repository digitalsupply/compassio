"""Tests for the next-item prefetch cache (Redis + in-process fallback)."""

from app.models import Assessment, UserRole
from app.next_cache import (
    LOCAL_MAX_ITEMS,
    cache_key,
    clear_local_cache,
    prefetch_next,
    read_next,
    write_next,
)
from tests.conftest import auth_token, create_user


async def test_prefetch_writes_then_cache_is_consumed(client, db):
    clear_local_cache()
    student = await create_user(db, UserRole.STUDENT, "stu_cache_prefetch")
    assessment = Assessment(user_id=student.id, scale_id="mht")
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)

    await prefetch_next(assessment.id, session=db)

    payload = await read_next(assessment.id)
    assert payload is not None
    assert "item_id" in payload
    assert payload["source"] == "rule_coverage"  # coverage phase = deterministic
    assert payload["created_at"]

    # One-shot consumption: the key is deleted after a hit.
    assert await read_next(assessment.id) is None


async def test_write_then_read_roundtrip():
    clear_local_cache()
    await write_next(123456, {"item_id": 7, "transition": "hi", "source": "llm", "created_at": "t"})
    payload = await read_next(123456)
    assert payload == {"item_id": 7, "transition": "hi", "source": "llm", "created_at": "t"}
    assert await read_next(123456) is None


async def test_local_cache_respects_capacity():
    clear_local_cache()
    for i in range(LOCAL_MAX_ITEMS + 50):
        await write_next(i, {"item_id": i, "transition": None, "source": "llm", "created_at": "t"})
    # Oldest entries evicted, newest retained.
    assert await read_next(0) is None
    kept = await read_next(LOCAL_MAX_ITEMS + 49)
    assert kept is not None and kept["item_id"] == LOCAL_MAX_ITEMS + 49
    clear_local_cache()


async def test_next_uses_prefetched_cache_hit(client, db):
    clear_local_cache()
    student = await create_user(db, UserRole.STUDENT, "stu_cache_http")
    token = await auth_token(client, "stu_cache_http")
    headers = {"Authorization": f"Bearer {token}"}

    start = await client.post("/api/assess/start", json={"scale_id": "mht"}, headers=headers)
    assert start.status_code == 200
    aid = start.json()["assessment_id"]

    # Seed a deliberate (non-rule-first) item to prove the cache is used.
    await write_next(
        aid,
        {"item_id": 77, "transition": "cached!", "source": "llm", "created_at": "t"},
    )

    nxt = await client.get(f"/api/assess/{aid}/next", headers=headers)
    assert nxt.status_code == 200
    data = nxt.json()
    assert data["item_id"] == 77
    assert data["transition"] == "cached!"

    # Cache consumed: a second call recomputes deterministically.
    nxt2 = await client.get(f"/api/assess/{aid}/next", headers=headers)
    assert nxt2.status_code == 200
    assert nxt2.json()["item_id"] != 77


async def test_cache_key_format():
    assert cache_key(42) == "compassio:next:42"
