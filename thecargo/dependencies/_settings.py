import os

_jwt_secret: str | None = None
_redis_url: str | None = None
_redis_client = None


def set_jwt_secret(secret: str):
    global _jwt_secret
    _jwt_secret = secret


def get_jwt_secret() -> str:
    if _jwt_secret:
        return _jwt_secret
    return os.environ.get("JWT_SECRET_KEY", "change-me")


def set_redis_url(url: str):
    """Each service calls this at startup so thecargo caching helpers share a
    single connection pool per process. Downstream libs lazily `from_url`
    when they first need Redis."""
    global _redis_url, _redis_client
    _redis_url = url
    _redis_client = None  # force re-init next time


def _get_redis_url() -> str:
    return _redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def get_redis():
    """Lazy singleton Redis connection scoped to this process."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(_get_redis_url(), decode_responses=True, max_connections=20)
    return _redis_client
