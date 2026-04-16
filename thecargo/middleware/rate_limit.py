import time
from dataclasses import dataclass, field

import redis.asyncio as aioredis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)
local current = redis.call('ZCARD', key)

if current >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local reset_at = 0
    if #oldest > 0 then
        reset_at = tonumber(oldest[2]) + window
    end
    return {current, reset_at}
end

redis.call('ZADD', key, now, now .. ':' .. math.random(1000000))
redis.call('EXPIRE', key, window)
local new_count = redis.call('ZCARD', key)
return {new_count, 0}
"""

SKIP_PREFIXES = ("/health", "/", "/api/internal/")


@dataclass
class RateLimitConfig:
    default_limit: int = 100
    default_window: int = 60
    auth_limit: int = 30
    auth_window: int = 60
    redis_url: str = "redis://localhost:6379/0"
    enabled: bool = True
    custom_rules: dict[str, tuple[int, int]] = field(default_factory=dict)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: RateLimitConfig):
        super().__init__(app)
        self.config = config
        self._redis: aioredis.Redis | None = None
        self._script_sha: str | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.config.redis_url,
                decode_responses=True,
                max_connections=20,
            )
            self._script_sha = await self._redis.script_load(SLIDING_WINDOW_SCRIPT)
        return self._redis

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _resolve_limit(self, path: str) -> tuple[int, int]:
        for prefix, (limit, window) in self.config.custom_rules.items():
            if path.startswith(prefix):
                return limit, window

        if "/auth/" in path or path.endswith("/auth"):
            return self.config.auth_limit, self.config.auth_window

        return self.config.default_limit, self.config.default_window

    def _should_skip(self, path: str) -> bool:
        if path == "/" or path == "/health":
            return True
        if path.startswith("/api/internal/"):
            return True
        return False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.config.enabled:
            return await call_next(request)

        path = request.url.path

        if self._should_skip(path):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        limit, window = self._resolve_limit(path)
        path_prefix = path.split("/")[:4]
        path_key = "/".join(path_prefix)
        redis_key = f"ratelimit:{client_ip}:{path_key}"
        now = time.time()

        try:
            r = await self._get_redis()
            result = await r.evalsha(self._script_sha, 1, redis_key, limit, window, now)
            current_count = int(result[0])
            reset_at = float(result[1])

            if reset_at > 0:
                retry_after = max(1, int(reset_at - now))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests"},
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(reset_at)),
                    },
                )

            response = await call_next(request)
            remaining = max(0, limit - current_count)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(int(now + window))
            return response

        except (aioredis.ConnectionError, aioredis.TimeoutError, aioredis.RedisError):
            return await call_next(request)


def rate_limit(limit: int = 10, window: int = 60):
    async def dependency(request: Request):
        redis_url = getattr(request.app.state, "rate_limit_redis_url", "redis://localhost:6379/0")
        r = aioredis.from_url(redis_url, decode_responses=True)
        try:
            client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if not client_ip:
                client_ip = request.client.host if request.client else "unknown"

            path = request.url.path
            redis_key = f"ratelimit:dep:{client_ip}:{path}"
            now = time.time()

            script = await r.script_load(SLIDING_WINDOW_SCRIPT)
            result = await r.evalsha(script, 1, redis_key, limit, window, now)
            current_count = int(result[0])
            reset_at = float(result[1])

            if reset_at > 0:
                retry_after = max(1, int(reset_at - now))
                raise _RateLimitExceeded(limit, retry_after, int(reset_at))

            request.state.rate_limit_remaining = max(0, limit - current_count)
            request.state.rate_limit_limit = limit
            request.state.rate_limit_reset = int(now + window)
        except _RateLimitExceeded:
            raise
        except Exception:
            pass
        finally:
            await r.aclose()

    return dependency


class _RateLimitExceeded(Exception):
    def __init__(self, limit: int, retry_after: int, reset_at: int):
        self.limit = limit
        self.retry_after = retry_after
        self.reset_at = reset_at


def _register_rate_limit_handler(app):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse as FastAPIJSONResponse

    @app.exception_handler(_RateLimitExceeded)
    async def handle_rate_limit(request: Request, exc: _RateLimitExceeded):
        return FastAPIJSONResponse(
            status_code=429,
            content={"detail": "Too Many Requests"},
            headers={
                "Retry-After": str(exc.retry_after),
                "X-RateLimit-Limit": str(exc.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(exc.reset_at),
            },
        )


def setup_rate_limit(app, config: RateLimitConfig):
    app.state.rate_limit_redis_url = config.redis_url
    app.add_middleware(RateLimitMiddleware, config=config)
    _register_rate_limit_handler(app)
