import pytest

from app.engine.adaptive import pick_next_item, select_candidate_order
from tests.conftest import auth_token, create_user
from app.models import UserRole


def test_select_candidate_order_starts_with_validity():
    import json
    from pathlib import Path
    scale = json.loads((Path(__file__).parent.parent / "app" / "scales" / "data" / "mht.json").read_text(encoding="utf-8"))
    ordered = select_candidate_order(scale, set())
    validity = scale["validity_scale"]["item_ids"]
    assert ordered[:len(validity)] == validity


async def test_adaptive_asks_all_items(client, db):
    student = await create_user(db, UserRole.STUDENT, "stu_adaptive")
    token = await auth_token(client, "stu_adaptive")
    headers = {"Authorization": f"Bearer {token}"}

    start = await client.post("/api/assess/start", json={"scale_id": "mht"}, headers=headers)
    assert start.status_code == 200
    aid = start.json()["assessment_id"]

    asked = set()
    for _ in range(110):
        nxt = await client.get(f"/api/assess/{aid}/next", headers=headers)
        assert nxt.status_code == 200
        data = nxt.json()
        if data["finished"]:
            break
        assert data["item_id"] is not None
        # answer
        resp = await client.post(
            f"/api/assess/{aid}/answer",
            json={"item_id": data["item_id"], "value": 0},
            headers=headers,
        )
        assert resp.status_code == 200
        asked.add(data["item_id"])

    assert len(asked) == 100


async def test_llm_failure_fallback(client, db):
    import json
    from pathlib import Path
    from app.llm.provider import LLMProvider
    from app.llm.service import resolve_provider

    scale = json.loads((Path(__file__).parent.parent / "app" / "scales" / "data" / "mht.json").read_text(encoding="utf-8"))

    class FailingProvider:
        async def chat(self, *args, **kwargs):
            raise RuntimeError("boom")

    chosen, transition, fallback = await pick_next_item(scale, {}, FailingProvider())
    assert chosen is not None
    assert fallback is True
