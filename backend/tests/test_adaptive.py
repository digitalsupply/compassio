import asyncio
import json
import re
from pathlib import Path

import pytest

from app.config import get_settings
from app.engine import checkpoint as checkpoint_mod
from app.engine.adaptive import pick_next_item, select_candidate_order
from app.observability import metrics as metrics_mod
from app.routers import assess as assess_module
from tests.conftest import auth_token, create_user
from app.models import UserRole

DATA_DIR = Path(__file__).parent.parent / "app" / "scales" / "data"


def _load_scale(name: str) -> dict:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


class RecordingProvider:
    """Mock LLM provider that records calls and emits a scripted behaviour."""

    def __init__(self, behavior: str = "valid"):
        self.behavior = behavior
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        user = messages[-1]["content"]
        ids = [int(x) for x in re.findall(r"item_id['\"]?\s*:\s*(\d+)", user)]
        if self.behavior == "invalid_json":
            return {"content": "not-json"}
        if self.behavior == "timeout":
            raise asyncio.TimeoutError()
        if self.behavior == "outside_ids":
            # Include an id that is NOT in the candidate set; it must be dropped.
            return {"content": {"ordered_ids": [999999] + ids[:1], "transition": "ok"}}
        # valid: reverse the candidate order to prove the LLM re-ranking is used.
        return {"content": {"ordered_ids": list(reversed(ids)), "transition": "加油"}}

    @property
    def config(self):  # for model label extraction
        return type("Cfg", (), {"model": "mock-model"})()


def _inject_provider(monkeypatch, provider):
    async def _fake_resolve(db=None):  # noqa: ANN001
        return provider

    monkeypatch.setattr(assess_module, "resolve_provider", _fake_resolve)


async def _run_full_flow(
    client, headers, scale_id: str, value: int, limit: int = 140, provider=None
):
    start = await client.post(
        "/api/assess/start", json={"scale_id": scale_id}, headers=headers
    )
    assert start.status_code == 200, start.text
    aid = start.json()["assessment_id"]

    answered = set()
    sources = []
    records = []  # (source, provider.calls at that step)
    for _ in range(limit):
        nxt = await client.get(f"/api/assess/{aid}/next", headers=headers)
        assert nxt.status_code == 200, nxt.text
        data = nxt.json()
        if data["finished"]:
            break
        sources.append(data.get("source"))
        records.append((data.get("source"), provider.calls if provider else None))
        resp = await client.post(
            f"/api/assess/{aid}/answer",
            json={"item_id": data["item_id"], "value": value},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        answered.add(data["item_id"])
    return aid, answered, sources, records


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

    scale = json.loads((Path(__file__).parent.parent / "app" / "scales" / "data" / "mht.json").read_text(encoding="utf-8"))

    class FailingProvider:
        def __init__(self):
            self.calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("boom")

    # Exit the coverage phase (>=2 answered per subscale) so the LLM is invoked.
    answered = {}
    for sub in scale["subscales"]:
        for iid in sub["item_ids"][:2]:
            answered[iid] = 0

    provider = FailingProvider()
    chosen, transition, fallback, source = await pick_next_item(scale, answered, provider)
    assert provider.calls == 1
    assert chosen is not None
    assert fallback is True
    assert source == "rule_fallback"


async def test_coverage_phase_skips_llm():
    import json
    from pathlib import Path

    scale = json.loads((Path(__file__).parent.parent / "app" / "scales" / "data" / "mht.json").read_text(encoding="utf-8"))

    class CountingProvider:
        def __init__(self):
            self.calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            return {"content": {"item_id": 1, "transition": "hi"}}

    provider = CountingProvider()
    # Empty answers => still in the per-dimension coverage phase.
    chosen, transition, fallback, source = await pick_next_item(scale, {}, provider)
    assert provider.calls == 0
    assert chosen is not None
    assert source == "rule_coverage"
    assert fallback is False


# ---------------------------------------------------------------------------
# 任务书 §5：融合策略的 6 项测试
# ---------------------------------------------------------------------------


async def test_fusion_call_count_bounded_and_coverage_free(client, db, monkeypatch):
    """① fusion + 计数 provider：100 题 MHT 的 LLM 调用落在 [4, 10]，覆盖阶段为 0。"""
    checkpoint_mod.clear_local_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "adaptive_strategy", "fusion")
    monkeypatch.setattr(settings, "adaptive_llm_interval_min", 12)
    monkeypatch.setattr(settings, "adaptive_llm_interval_max", 20)

    provider = RecordingProvider("valid")
    _inject_provider(monkeypatch, provider)

    student = await create_user(db, UserRole.STUDENT, "stu_fusion_count")
    token = await auth_token(client, "stu_fusion_count")
    headers = {"Authorization": f"Bearer {token}"}

    aid, answered, sources, records = await _run_full_flow(
        client, headers, "mht", value=0, provider=provider
    )

    assert len(answered) == 100
    assert 4 <= provider.calls <= 10, f"unexpected LLM calls: {provider.calls}"

    coverage = [calls for src, calls in records if src == "rule_coverage"]
    assert coverage, "expected a deterministic coverage phase"
    assert all(calls == 0 for calls in coverage), "coverage phase must not call the LLM"

    # Every consult maps to exactly one llm_fusion/rule_fallback result.
    assert sources.count("llm_fusion") + sources.count("rule_fallback") == provider.calls

    finish = await client.post(f"/api/assess/{aid}/finish", headers=headers)
    assert finish.status_code == 200
    assert finish.json()["is_valid"] is True


async def test_rules_only_never_calls_llm(client, db, monkeypatch):
    """② rules_only：全流程 LLM 调用数 = 0。"""
    checkpoint_mod.clear_local_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "adaptive_strategy", "rules_only")

    provider = RecordingProvider("valid")
    _inject_provider(monkeypatch, provider)

    student = await create_user(db, UserRole.STUDENT, "stu_rules_only")
    token = await auth_token(client, "stu_rules_only")
    headers = {"Authorization": f"Bearer {token}"}

    aid, answered, sources, _ = await _run_full_flow(
        client, headers, "mht", value=0, provider=provider
    )

    assert len(answered) == 100
    assert provider.calls == 0
    assert all(src in ("rule_coverage", "rule_weighted") for src in sources)

    finish = await client.post(f"/api/assess/{aid}/finish", headers=headers)
    assert finish.status_code == 200


async def test_fusion_invalid_json_falls_back_and_flow_continues(client, db, monkeypatch):
    """③-a 检查点返回非法 JSON：回退规则、流程不中断、fallback_total 递增。"""
    checkpoint_mod.clear_local_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "adaptive_strategy", "fusion")

    provider = RecordingProvider("invalid_json")
    _inject_provider(monkeypatch, provider)

    fallback_before = (
        metrics_mod.llm_fallback_total.labels("pick_next_checkpoint")._value.get()
    )

    student = await create_user(db, UserRole.STUDENT, "stu_fusion_badjson")
    token = await auth_token(client, "stu_fusion_badjson")
    headers = {"Authorization": f"Bearer {token}"}

    aid, answered, sources, _ = await _run_full_flow(
        client, headers, "mht", value=0, provider=provider
    )

    fallback_after = (
        metrics_mod.llm_fallback_total.labels("pick_next_checkpoint")._value.get()
    )

    assert provider.calls >= 1
    assert len(answered) == 100
    assert sources.count("rule_fallback") == provider.calls
    assert fallback_after - fallback_before == provider.calls

    finish = await client.post(f"/api/assess/{aid}/finish", headers=headers)
    assert finish.status_code == 200


async def test_fusion_timeout_falls_back():
    """③-b 检查点超时：回退规则、fallback_total 递增。"""
    scale = _load_scale("mht")
    answered = {
        iid: 0 for sub in scale["subscales"] for iid in sub["item_ids"][:2]
    }

    fallback_before = (
        metrics_mod.llm_fallback_total.labels("pick_next_checkpoint")._value.get()
    )
    provider = RecordingProvider("timeout")
    chosen, transition, fallback, source = await pick_next_item(scale, answered, provider)
    fallback_after = (
        metrics_mod.llm_fallback_total.labels("pick_next_checkpoint")._value.get()
    )

    assert provider.calls == 1
    assert chosen is not None
    assert fallback is True
    assert source == "rule_fallback"
    assert fallback_after - fallback_before == 1


async def test_fusion_filters_ids_outside_candidate_set():
    """④ ordered_ids 含候选集外 id：被过滤丢弃，不抛错。"""
    scale = _load_scale("mht")
    answered = {
        iid: 0 for sub in scale["subscales"] for iid in sub["item_ids"][:2]
    }
    candidates = select_candidate_order(scale, set(answered))[:20]

    provider = RecordingProvider("outside_ids")
    chosen, transition, fallback, source = await pick_next_item(
        scale, answered, provider
    )

    assert provider.calls == 1
    assert fallback is False
    assert source == "llm_fusion"
    # 999999 must be dropped; only the in-set id survives -> it wins.
    assert chosen == candidates[0]
    assert chosen != 999999


async def test_three_scales_complete_and_finish_regression(client, db, monkeypatch):
    """⑤ 题量/计分回归：三量表答满并 finish，is_valid True。"""
    checkpoint_mod.clear_local_state()
    settings = get_settings()
    # Default fusion strategy, no provider injected => pure rules, still must pass.
    monkeypatch.setattr(settings, "adaptive_strategy", "fusion")

    cases = [
        ("mht", UserRole.STUDENT, 0, 100),
        ("mssmhs", UserRole.STUDENT, 1, 60),
        ("teacher_ref", UserRole.TEACHER, 1, 60),
    ]
    for scale_id, role, value, total in cases:
        username = f"stu_reg_{scale_id}"
        await create_user(db, role, username)
        token = await auth_token(client, username)
        headers = {"Authorization": f"Bearer {token}"}

        aid, answered, _sources, _records = await _run_full_flow(
            client, headers, scale_id, value
        )
        assert len(answered) == total, f"{scale_id}: answered {len(answered)}"

        finish = await client.post(f"/api/assess/{aid}/finish", headers=headers)
        assert finish.status_code == 200, finish.text
        assert finish.json()["is_valid"] is True


async def test_metrics_expose_adaptive_fusion_counters(client):
    """⑥ /metrics 中可 grep 到 consulted / skipped / requests_total。"""
    metrics_mod.inc_llm_consulted()
    metrics_mod.inc_llm_skipped()
    metrics_mod.inc_llm_request("pick_next_checkpoint", "fusion")

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "compassio_adaptive_llm_consulted_total" in body
    assert "compassio_adaptive_llm_skipped_total" in body
    assert "compassio_llm_requests_total" in body
