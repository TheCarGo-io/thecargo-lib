"""Shared cache-aside helpers.

Every service wires its Redis URL via
``thecargo.dependencies._settings.set_redis_url(...)`` at startup.
This module exposes three primitives:

    await cache_aside(key, loader, ttl=...)   # lazy-load + populate
    await cache_invalidate(*keys)              # explicit purge
    await cache_set(key, value, ttl=...)       # write-through

Design choices:

- **Fail open.** If Redis is unreachable we log and fall through to the
  loader. Services keep serving; we lose cache benefit but not correctness.
- **Serialization.** JSON by default. Callers can pass custom serialize/
  deserialize for binary payloads or type-preserving codecs.
- **Single in-process singleton.** ``_settings.get_redis()`` returns a
  pooled connection (see ``redis.asyncio.from_url``), so each worker
  holds at most ~20 Redis sockets.

We intentionally *do not* implement single-flight / distributed locks
here — at our traffic level the thundering-herd risk is a rounding
error. Add it if we ever see >1000 cache-miss RPS on a hot key.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, TypeVar

from thecargo.dependencies._settings import get_redis

T = TypeVar("T")

log = logging.getLogger("thecargo.cache")


def _default_serialize(value: Any) -> str:
    return json.dumps(value, default=str)


def _default_deserialize(raw: str) -> Any:
    return json.loads(raw)


async def cache_aside(
    key: str,
    loader: Callable[[], Awaitable[T]],
    ttl: int = 300,
    *,
    serialize: Callable[[T], str] = _default_serialize,
    deserialize: Callable[[str], T] = _default_deserialize,
) -> T:
    """Return ``key`` from Redis; on miss, call ``loader()`` and populate.

    Contract:
        - Redis errors never propagate — loader runs and its result is returned.
        - ``None`` is not cacheable (callers must wrap Optional results
          in a sentinel or use a negative-cache key).
    """
    try:
        redis = await get_redis()
        cached = await redis.get(key)
        if cached is not None:
            return deserialize(cached)
    except Exception as exc:
        log.warning("cache_get_failed key=%s err=%s", key, exc)

    value = await loader()

    try:
        redis = await get_redis()
        await redis.setex(key, ttl, serialize(value))
    except Exception as exc:
        log.warning("cache_set_failed key=%s err=%s", key, exc)

    return value


async def cache_invalidate(*keys: str) -> None:
    """Best-effort delete. Silently swallows Redis failures."""
    if not keys:
        return
    try:
        redis = await get_redis()
        await redis.delete(*keys)
    except Exception as exc:
        log.warning("cache_invalidate_failed keys=%s err=%s", keys, exc)


async def cache_set(
    key: str,
    value: Any,
    ttl: int = 300,
    *,
    serialize: Callable[[Any], str] = _default_serialize,
) -> None:
    """Write-through helper for callers that already have a fresh value."""
    try:
        redis = await get_redis()
        await redis.setex(key, ttl, serialize(value))
    except Exception as exc:
        log.warning("cache_set_failed key=%s err=%s", key, exc)


async def cache_get(key: str) -> str | None:
    """Raw GET — returns None on miss or Redis failure. Caller decodes."""
    try:
        redis = await get_redis()
        return await redis.get(key)
    except Exception:
        return None
