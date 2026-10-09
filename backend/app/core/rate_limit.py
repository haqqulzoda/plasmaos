"""Fixed-window rate limits for public endpoints, kept in Redis (R3).

One counter per (scope, client, window): ``plasma:ratelimit:<scope>:<client>:<window index>``,
expiring with its window. If Redis cannot be reached the request is allowed and a warning is
logged: the limit is defence in depth (the tokens it guards are 256-bit random), and Redis
being down already fails /health/ready.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None


def _redis() -> Any:
    global _client
    if _client is None:
        from redis.asyncio import Redis

        _client = Redis.from_url(
            os.environ.get("AUTH_REPLAY_REDIS_URL", "redis://127.0.0.1:6379/0"),
            socket_connect_timeout=1, socket_timeout=1,
        )
    return _client


async def hit(
    scope: str, identifier: str, *, limit: int, window_seconds: int, client: Any = None, now: float | None = None,
) -> int | None:
    """Count one request. Returns the seconds until the window resets when over ``limit``, else None."""
    moment = time.time() if now is None else now
    window = int(moment // window_seconds)
    key = f"plasma:ratelimit:{scope}:{identifier}:{window}"
    try:
        redis = client if client is not None else _redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds + 5)
    except Exception:  # noqa: BLE001 - fail open, see the module docstring
        logger.warning("rate_limit_unavailable scope=%s", scope)
        return None
    if count > limit:
        return max(1, int((window + 1) * window_seconds - moment))
    return None
