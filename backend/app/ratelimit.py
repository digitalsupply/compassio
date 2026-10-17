"""Login brute-force protection backed by Redis (P0 hardening).

Counts *failed* login attempts per username inside a sliding window; once the
count reaches ``LOGIN_RATE_LIMIT_ATTEMPTS`` the account is temporarily locked
(a 429 is returned until the window expires). A successful login clears the
counter.

Redis is optional, consistent with the rest of the codebase's graceful
degradation policy: if Redis is unavailable every check returns "not limited"
and failures are silently dropped, so a Redis outage can never block logins.
Only per-username counters are stored (hashed), never passwords.
"""

from __future__ import annotations

import hashlib
import logging

from app.config import get_settings
from app.db import get_redis

logger = logging.getLogger("compassio.ratelimit")

KEY_PREFIX = "compassio:login:fail:"


def _key(username: str) -> str:
    # Hash the username so Redis does not hold account identifiers at rest.
    digest = hashlib.sha256((username or "").strip().lower().encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}{digest}"


async def is_login_locked(username: str) -> bool:
    """True when ``username`` has too many recent failures. Redis-down => False."""
    client = get_redis()
    if client is None:
        return False
    try:
        raw = await client.get(_key(username))
    except Exception:
        return False
    if raw is None:
        return False
    try:
        return int(raw) >= max(1, get_settings().login_rate_limit_attempts)
    except (TypeError, ValueError):
        return False


async def record_login_failure(username: str) -> None:
    """Increment the failure counter and refresh the sliding-window TTL."""
    client = get_redis()
    if client is None:
        return
    try:
        key = _key(username)
        # INCR + EXPIRE 走同一事务：避免 INCR 成功而 EXPIRE 失败留下无 TTL 的键，
        # 那会造成该用户名被永久锁定。
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, max(1, get_settings().login_rate_limit_window_seconds))
        await pipe.execute()
    except Exception:
        logger.warning("login rate-limit increment failed", exc_info=True)


async def clear_login_failures(username: str) -> None:
    """Reset the counter after a successful login."""
    client = get_redis()
    if client is None:
        return
    try:
        await client.delete(_key(username))
    except Exception:
        # 清不掉计数不影响本次成功登录，只是可能让窗口稍晚结束。
        logger.debug("login rate-limit reset failed", exc_info=True)


__all__ = [
    "KEY_PREFIX",
    "is_login_locked",
    "record_login_failure",
    "clear_login_failures",
]
