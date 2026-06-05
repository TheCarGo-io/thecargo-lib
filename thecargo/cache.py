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
    try:
        redis = await get_redis()
        await redis.setex(key, ttl, serialize(value))
    except Exception as exc:
        log.warning("cache_set_failed key=%s err=%s", key, exc)


async def cache_get(key: str) -> str | None:
    try:
        redis = await get_redis()
        return await redis.get(key)
    except Exception:
        return None
