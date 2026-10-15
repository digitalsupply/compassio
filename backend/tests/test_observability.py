"""Tests for LGTM instrumentation: /metrics, request-id correlation."""

from app.models import UserRole
from app.observability import metrics as m
from tests.conftest import auth_token, create_user


KEY_METRIC_NAMES = (
    "compassio_http_request_duration_seconds",
    "compassio_http_requests_total",
    "compassio_llm_request_duration_seconds",
    "compassio_llm_fallback_total",
    "compassio_next_cache_total",
    "compassio_next_llm_wait_seconds",
    "compassio_dependency_up",
)


async def test_metrics_endpoint_exposes_key_metrics(client):
    # Produce at least one sample for each family we assert on.
    await client.get("/api/health")  # http + dependency gauges
    m.inc_next_cache("hit")
    m.observe_llm("pick_next", "test-model", "ok", 0.01)
    m.inc_fallback("pick_next")

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    for name in KEY_METRIC_NAMES:
        assert name in body, f"metric missing from /metrics: {name}"


async def test_request_id_header_is_echoed(client):
    resp = await client.get("/api/health", headers={"X-Request-ID": "test-req-123"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == "test-req-123"

    # A generated id is returned when the client does not supply one.
    resp2 = await client.get("/api/health")
    assert resp2.headers.get("X-Request-ID")


async def test_http_metrics_use_route_template(client):
    """Route label must be the template (ids stripped), not the concrete path."""
    await client.get("/api/health")
    # Unauthenticated request still matches the route -> template label.
    await client.get("/api/assess/12345/next")
    resp = await client.get("/metrics")
    body = resp.text
    assert 'route="/api/health"' in body
    assert 'route="/api/assess/{id}/next"' in body
    assert "/api/assess/12345/next" not in body


def _hist_count(name: str) -> float:
    for line in m.metrics_payload().decode().splitlines():
        if line.startswith(name + " "):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


async def test_next_rule_path_does_not_observe_llm_wait(client, db):
    """问题 4：规则路径（无 provider / 覆盖阶段）绝不观测 LLM 等待直方图。"""
    student = await create_user(db, UserRole.STUDENT, "stu_wait_metric")
    token = await auth_token(client, "stu_wait_metric")
    headers = {"Authorization": f"Bearer {token}"}
    start = await client.post("/api/assess/start", json={"scale_id": "mht"}, headers=headers)
    assert start.status_code == 200
    aid = start.json()["assessment_id"]

    before = _hist_count("compassio_next_llm_wait_seconds_count")
    observed_sources = []
    for _ in range(6):
        nxt = await client.get(f"/api/assess/{aid}/next", headers=headers)
        assert nxt.status_code == 200
        data = nxt.json()
        if data["finished"]:
            break
        observed_sources.append(data.get("source"))
        await client.post(
            f"/api/assess/{aid}/answer",
            json={"item_id": data["item_id"], "value": 0},
            headers=headers,
        )
    after = _hist_count("compassio_next_llm_wait_seconds_count")

    assert observed_sources, "应至少取到一题"
    assert all(src != "llm_fusion" and src != "llm" for src in observed_sources)
    assert after == before, "规则路径不得观测 compassio_next_llm_wait_seconds"


async def test_next_cache_miss_carries_reason_label(client, db):
    """问题 4：cache miss 事件带 reason 维度（no_prefetch）。"""
    student = await create_user(db, UserRole.STUDENT, "stu_reason_metric")
    token = await auth_token(client, "stu_reason_metric")
    headers = {"Authorization": f"Bearer {token}"}
    start = await client.post("/api/assess/start", json={"scale_id": "mht"}, headers=headers)
    aid = start.json()["assessment_id"]
    await client.get(f"/api/assess/{aid}/next", headers=headers)

    body = (await client.get("/metrics")).text
    assert 'reason="no_prefetch"' in body
