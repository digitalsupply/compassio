"""LLM 依赖探针：30s 巡检必须免额度，付费 chat ping 必须被节流。

背景：之前 30s 巡检每次都调用真实推理接口（stage=ping），24 小时不间断，
单日约 1.6 万次请求，纯属额度浪费。现在 30s 巡检只做免额度探活，
付费 ping 由 LLM_PING_INTERVAL_SECONDS 节流（0 = 关闭）。
"""

from types import SimpleNamespace

import httpx
import pytest

from app import main as main_mod
from app.llm.provider import LLMProvider, ProviderConfig


def _provider(handler, *, provider_key="opencode-go", extra_headers=None, api_key="oc_sk_test"):
    cfg = ProviderConfig(
        provider_key=provider_key,
        base_url="https://llm.example.invalid/v1",
        api_key=api_key,
        model="deepseek-v4.1-flash",
        extra_headers=(
            {"x-opencode-session": "{{uuid}}"} if extra_headers is None else extra_headers
        ),
    )
    provider = LLMProvider(cfg)
    transport = httpx.MockTransport(handler)
    provider._client = lambda: httpx.AsyncClient(transport=transport, timeout=5)  # type: ignore[assignment]
    return provider


async def test_reachable_is_token_free_and_detects_valid_credential():
    """合法凭据：网关在校验后、推理前以 400 拒绝 → 判为 ok 且不发 messages。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["session"] = request.headers.get("x-opencode-session")
        seen["body"] = request.content.decode()
        return httpx.Response(
            400,
            json={"error": {"type": "invalid_request_error", "message": "messages is required"}},
        )

    ok, outcome = await _provider(handler).reachable()

    assert (ok, outcome) == (True, "ok")
    assert seen["url"] == "https://llm.example.invalid/v1/chat/completions"
    assert seen["auth"] == "Bearer oc_sk_test"
    assert seen["session"], "opencode-go 需要 x-opencode-session"
    assert "messages" not in seen["body"], "探活不得带上 messages，否则会真推理"
    assert "deepseek-v4.1-flash" in seen["body"]


@pytest.mark.parametrize("status", [401, 403])
async def test_reachable_reports_auth_error_for_rejected_credential(status):
    """被禁用的 key（此前线上的真实故障）必须判为 auth_error。"""
    ok, outcome = await _provider(
        lambda request: httpx.Response(status, json={"error": {"type": "server_error"}})
    ).reachable()
    assert (ok, outcome) == (False, "auth_error")


async def test_reachable_reports_unreachable_on_5xx_and_network_error():
    ok, outcome = await _provider(
        lambda request: httpx.Response(503, text="upstream down")
    ).reachable()
    assert (ok, outcome) == (False, "unreachable")

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    ok, outcome = await _provider(boom).reachable()
    assert (ok, outcome) == (False, "unreachable")


@pytest.mark.parametrize("status", [404, 405])
async def test_reachable_treats_missing_endpoint_as_down(status):
    """路径写错时网关返回 404，不能误判为“凭据有效 = 依赖可用”。"""
    ok, outcome = await _provider(lambda request: httpx.Response(status)).reachable()
    assert (ok, outcome) == (False, "unreachable")


async def test_reachable_treats_rate_limit_as_up():
    """429 说明凭据有效、只是被限流：依赖本身仍算可达。"""
    ok, outcome = await _provider(lambda request: httpx.Response(429)).reachable()
    assert (ok, outcome) == (True, "ok")


async def test_reachable_flags_missing_session_header_without_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400)

    ok, outcome = await _provider(handler, extra_headers={}).reachable()

    assert (ok, outcome) == (False, "config_error")
    assert calls == [], "配置错误不该发出请求"


async def test_reachable_skips_session_requirement_for_other_providers():
    ok, outcome = await _provider(
        lambda request: httpx.Response(400, text="messages is required"),
        provider_key="deepseek",
        extra_headers={},
    ).reachable()
    assert (ok, outcome) == (True, "ok")


class _FakeSharedState:
    """内存版 Redis 共享状态：健康记录 + SET NX EX 名额。"""

    def __init__(self):
        self.health: str | None = None
        self.slots: dict[str, int] = {}

    async def shared(self):
        return None if self.health is None else self.health == "1"

    async def store(self, ok, ttl):
        self.health = "1" if ok else "0"

    async def acquire(self, key, ttl):
        if key in self.slots:
            return False
        self.slots[key] = ttl
        return True

    def expire_health(self):
        self.health = None


def _patch_shared(monkeypatch, state: _FakeSharedState):
    monkeypatch.setattr(main_mod, "_shared_llm_health", state.shared)
    monkeypatch.setattr(main_mod, "_store_shared_llm_health", state.store)
    monkeypatch.setattr(main_mod, "_acquire_slot", state.acquire)


async def _fake_settings(monkeypatch, *, reach=900, ping=1800):
    monkeypatch.setattr(
        main_mod,
        "get_settings",
        lambda: SimpleNamespace(
            llm_reachability_interval_seconds=reach,
            llm_ping_interval_seconds=ping,
            adaptive_strategy="fusion",
        ),
    )


async def test_llm_checks_are_throttled_and_shared(monkeypatch):
    """探活按 900s 节流，付费 ping 按 1800s 节流，且结果跨 worker 共享。"""
    free, deep = [], []

    async def fake_free(provider):
        free.append(provider)
        return True

    async def fake_deep(provider):
        deep.append(provider)
        return True

    monkeypatch.setattr(main_mod, "_probe_llm_reachable", fake_free)
    monkeypatch.setattr(main_mod, "_probe_llm", fake_deep)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK", 0.0)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK_TTL", 0)
    state = _FakeSharedState()
    _patch_shared(monkeypatch, state)
    await _fake_settings(monkeypatch)

    provider = object()
    assert await main_mod._maybe_llm_check(provider) is True
    assert (len(free), len(deep)) == (1, 1)  # 首次：两者都到期

    # 共享记录新鲜：任何 worker 都不再访问网关，直接拿到同一答案
    for _ in range(5):
        assert await main_mod._maybe_llm_check(provider) is True
    assert (len(free), len(deep)) == (1, 1)

    # 900s 后：共享记录与探活名额一起过期，但付费名额（1800s）仍被占用
    state.expire_health()
    del state.slots[main_mod.LLM_PROBE_LOCK_KEY]
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK", 0.0)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK_TTL", 0)  # 模拟 900s 已过
    assert await main_mod._maybe_llm_check(provider) is True
    assert (len(free), len(deep)) == (2, 1)  # 只补免额度探活，付费 ping 未到期


async def test_probe_slot_held_by_another_worker_skips_probing(monkeypatch):
    """别的 worker 抢到名额时本轮不做任何网络检查。"""
    calls = []

    async def fake_free(provider):  # pragma: no cover - must never run
        calls.append(provider)
        return True

    monkeypatch.setattr(main_mod, "_probe_llm_reachable", fake_free)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK", 0.0)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK_TTL", 0)
    state = _FakeSharedState()
    state.slots[main_mod.LLM_PROBE_LOCK_KEY] = 900  # 名额已被占用
    _patch_shared(monkeypatch, state)
    await _fake_settings(monkeypatch)

    assert await main_mod._maybe_llm_check(object()) is None
    assert calls == []


async def test_failed_reachability_probe_skips_billed_ping(monkeypatch):
    deep = []

    async def fake_free(provider):
        return False

    async def fake_deep(provider):  # pragma: no cover - must never run
        deep.append(provider)
        return True

    monkeypatch.setattr(main_mod, "_probe_llm_reachable", fake_free)
    monkeypatch.setattr(main_mod, "_probe_llm", fake_deep)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK", 0.0)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK_TTL", 0)
    state = _FakeSharedState()
    _patch_shared(monkeypatch, state)
    await _fake_settings(monkeypatch)

    assert await main_mod._maybe_llm_check(object()) is False
    assert deep == []
    assert state.health == "0"  # 失败结果同样共享给所有 worker


async def test_llm_checks_can_be_disabled(monkeypatch):
    async def boom(provider):  # pragma: no cover - must never run
        raise AssertionError("interval=0 时不得访问网关")

    monkeypatch.setattr(main_mod, "_probe_llm_reachable", boom)
    monkeypatch.setattr(main_mod, "_probe_llm", boom)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK", 0.0)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK_TTL", 0)
    state = _FakeSharedState()
    _patch_shared(monkeypatch, state)
    await _fake_settings(monkeypatch, reach=0, ping=0)

    assert await main_mod._maybe_llm_check(object()) is None


async def test_health_endpoint_reports_shared_state(client, monkeypatch):
    """/api/health 读共享状态：两个 worker 不会再各说各话。"""
    async def healthy():
        return True

    monkeypatch.setattr(main_mod, "_shared_llm_health", healthy)
    assert (await client.get("/api/health")).json()["llm"] is True

    async def broken():
        return False

    monkeypatch.setattr(main_mod, "_shared_llm_health", broken)
    assert (await client.get("/api/health")).json()["llm"] is False


async def test_reachability_metric_is_exposed():
    from app.observability.metrics import inc_llm_reachability, metrics_payload

    inc_llm_reachability("ok")
    assert "compassio_llm_reachability_total" in metrics_payload().decode()


class _FlakyProvider:
    """按脚本返回 reachable() 结果的假 provider。"""

    class config:  # noqa: N801 - mimic provider.config.model
        model = "deepseek-v4.1-flash"

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def reachable(self):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result


async def test_transient_network_failure_is_retried(monkeypatch):
    """到网关的握手超时很常见（实测单次失败率约 1/3），必须重试后再判定。"""
    monkeypatch.setattr(main_mod, "LLM_PROBE_RETRY_DELAY_S", 0)
    provider = _FlakyProvider([(False, "unreachable"), (True, "ok")])

    assert await main_mod._probe_llm_reachable(provider) is True
    assert provider.calls == 2


async def test_persistent_failure_after_all_attempts(monkeypatch):
    monkeypatch.setattr(main_mod, "LLM_PROBE_RETRY_DELAY_S", 0)
    provider = _FlakyProvider([(False, "unreachable")])

    assert await main_mod._probe_llm_reachable(provider) is False
    assert provider.calls == main_mod.LLM_PROBE_ATTEMPTS


async def test_auth_error_is_not_retried(monkeypatch):
    """凭据被拒是确定性结论，重试没有意义。"""
    monkeypatch.setattr(main_mod, "LLM_PROBE_RETRY_DELAY_S", 0)
    provider = _FlakyProvider([(False, "auth_error")])

    assert await main_mod._probe_llm_reachable(provider) is False
    assert provider.calls == 1


async def _capture_shared_ttl(monkeypatch, probe_ok):
    stored = []

    async def fake_probe(provider):
        return probe_ok

    async def fake_ping(provider):
        return True

    async def store(ok, ttl):
        stored.append((ok, ttl))

    async def shared():
        return None

    async def acquire(key, ttl):
        return True

    monkeypatch.setattr(main_mod, "_probe_llm_reachable", fake_probe)
    monkeypatch.setattr(main_mod, "_probe_llm", fake_ping)
    monkeypatch.setattr(main_mod, "_store_shared_llm_health", store)
    monkeypatch.setattr(main_mod, "_shared_llm_health", shared)
    monkeypatch.setattr(main_mod, "_acquire_slot", acquire)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK", 0.0)
    monkeypatch.setattr(main_mod, "_LAST_LLM_CHECK_TTL", 0)
    await _fake_settings(monkeypatch)
    return stored


async def test_success_is_cached_for_full_interval(monkeypatch):
    stored = await _capture_shared_ttl(monkeypatch, True)
    assert await main_mod._maybe_llm_check(object()) is True
    assert stored == [(True, 900)]


async def test_failure_is_cached_briefly_so_it_recovers_fast(monkeypatch):
    """失败只记 60s：避免一次网络抖动让依赖状态挂满整个 900s 间隔。"""
    stored = await _capture_shared_ttl(monkeypatch, False)
    assert await main_mod._maybe_llm_check(object()) is False
    assert stored == [(False, main_mod.LLM_FAILURE_RETRY_SECONDS)]


async def test_ping_is_a_single_request_without_truncation_retry():
    """推理模型会把 max_tokens=5 全用在思考上：ping 不能因此重试第二次。"""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "", "reasoning_content": "…"}, "finish_reason": "length"}
                ]
            },
        )

    assert await _provider(handler).ping() is True
    assert len(requests) == 1, "一次 ping 只能产生一次上游推理调用"


async def test_ping_reports_failure_on_auth_error_and_network_error():
    ok = await _provider(lambda request: httpx.Response(401)).ping()
    assert ok is False

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert await _provider(boom).ping() is False


async def test_ping_flags_missing_session_header_without_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    assert await _provider(handler, extra_headers={}).ping() is False
    assert calls == []
