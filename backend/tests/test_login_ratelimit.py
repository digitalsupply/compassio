"""登录爆破防护（P0）：失败计数、锁定 429、成功清零、Redis 不可用时放行。"""

from app import ratelimit
from app.config import get_settings
from app.models import UserRole
from tests.conftest import create_user


class FakeRedis:
    """最小内存版 Redis：只实现限流用到的方法。"""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key):
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key, ttl):
        self.ttls[key] = ttl
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    """Buffers commands then runs them on execute(), mimicking redis-py."""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops = []

    def incr(self, key):
        self._ops.append(("incr", key))

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))

    async def execute(self):
        results = []
        for op in self._ops:
            results.append(await getattr(self._redis, op[0])(*op[1:]))
        return results


def _patch_redis(monkeypatch, fake) -> None:
    monkeypatch.setattr(ratelimit, "get_redis", lambda: fake)


async def test_login_locks_after_repeated_failures(client, db, monkeypatch):
    fake = FakeRedis()
    _patch_redis(monkeypatch, fake)
    await create_user(db, UserRole.STUDENT, "stu_lock")
    limit = get_settings().login_rate_limit_attempts

    for _ in range(limit):
        resp = await client.post(
            "/api/auth/login", json={"username": "stu_lock", "password": "nope"}
        )
        assert resp.status_code == 401

    # 达到上限后：即使密码正确也必须拒绝，避免用状态码探测密码。
    locked = await client.post(
        "/api/auth/login", json={"username": "stu_lock", "password": "nope"}
    )
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1

    good = await client.post(
        "/api/auth/login", json={"username": "stu_lock", "password": "Test1234!"}
    )
    assert good.status_code == 429


async def test_login_success_clears_failure_counter(client, db, monkeypatch):
    fake = FakeRedis()
    _patch_redis(monkeypatch, fake)
    await create_user(db, UserRole.STUDENT, "stu_clear")

    for _ in range(3):
        await client.post("/api/auth/login", json={"username": "stu_clear", "password": "x"})

    ok = await client.post(
        "/api/auth/login", json={"username": "stu_clear", "password": "Test1234!"}
    )
    assert ok.status_code == 200
    assert fake.store == {}, "成功登录后应清空失败计数"

    again = await client.post(
        "/api/auth/login", json={"username": "stu_clear", "password": "x"}
    )
    assert again.status_code == 401  # 计数已归零，未触发锁定


async def test_login_limit_is_per_username(client, db, monkeypatch):
    fake = FakeRedis()
    _patch_redis(monkeypatch, fake)
    await create_user(db, UserRole.STUDENT, "stu_a")
    await create_user(db, UserRole.STUDENT, "stu_b")
    for _ in range(get_settings().login_rate_limit_attempts + 1):
        await client.post("/api/auth/login", json={"username": "stu_a", "password": "x"})

    # 锁定只针对 stu_a，不影响其他账号。
    other = await client.post(
        "/api/auth/login", json={"username": "stu_b", "password": "Test1234!"}
    )
    assert other.status_code == 200


async def test_login_degrades_gracefully_without_redis(client, db, monkeypatch):
    _patch_redis(monkeypatch, None)
    await create_user(db, UserRole.STUDENT, "stu_noredis")
    for _ in range(get_settings().login_rate_limit_attempts + 5):
        resp = await client.post(
            "/api/auth/login", json={"username": "stu_noredis", "password": "x"}
        )
        assert resp.status_code == 401  # Redis 不可用 => 永远不锁
