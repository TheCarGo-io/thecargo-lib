import hmac
import logging
import math
import os
import time
from dataclasses import dataclass, field

import jwt
import redis.asyncio as aioredis
from fastapi import Request
from redis.exceptions import RedisError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

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

TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local state = redis.call('HMGET', key, 'tokens', 'at')
local tokens = tonumber(state[1]) or burst
local at = tonumber(state[2]) or now
tokens = math.min(burst, tokens + math.max(0, now - at) * rate)
local retry_ms = 0
if tokens >= 1 then
    tokens = tokens - 1
else
    retry_ms = math.ceil((1 - tokens) / rate * 1000)
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'at', tostring(now))
redis.call('PEXPIRE', key, math.ceil(burst / rate * 1000) + 1000)
return retry_ms
"""

SKIP_PREFIXES = ("/health", "/metrics")
PAUSE_AFTER_REDIS_ERROR = 5.0
REPORT_EVERY = 10.0


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


@dataclass
class RateLimitConfig:
    jwt_secret: str
    service_secret: str = ""
    redis_url: str = "redis://localhost:6379/0"
    jwt_algorithm: str = "HS256"
    mode: str = field(default_factory=lambda: os.environ.get("ORG_RATE_LIMIT_MODE") or "shadow")
    per_minute: int = field(default_factory=lambda: _env_int("ORG_RATE_LIMIT_PER_MINUTE", 600))
    burst: int = field(default_factory=lambda: _env_int("ORG_RATE_LIMIT_BURST", 200))
    service: str = field(default_factory=lambda: os.environ.get("SERVICE_NAME") or "unknown")


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, config: RateLimitConfig):
        self.app = app
        self.config = config
        self._redis: aioredis.Redis | None = None
        self._script = None
        self._paused_until = 0.0
        self._reported: dict[str, tuple[float, int]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.config.mode not in ("shadow", "enforce"):
            await self.app(scope, receive, send)
            return

        org_id = self._org_of(scope)
        retry_after = await self._take(org_id) if org_id else None
        if retry_after is None:
            await self.app(scope, receive, send)
            return

        self._report(org_id, scope)
        if self.config.mode == "shadow":
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            status_code=429,
            content={"detail": "Too Many Requests"},
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)

    def _org_of(self, scope: Scope) -> str | None:
        if scope["path"].startswith(SKIP_PREFIXES):
            return None
        headers = Headers(scope=scope)
        secret = headers.get("x-service-secret")
        if secret and self.config.service_secret and hmac.compare_digest(secret, self.config.service_secret):
            return None
        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return None
        try:
            payload = jwt.decode(auth[7:], self.config.jwt_secret, algorithms=[self.config.jwt_algorithm])
        except jwt.PyJWTError:
            return None
        org_id = payload.get("org_id")
        return str(org_id) if org_id else None

    async def _take(self, org_id: str) -> int | None:
        if time.monotonic() < self._paused_until:
            return None
        if self._redis is None:
            pool = aioredis.BlockingConnectionPool.from_url(
                self.config.redis_url,
                max_connections=20,
                timeout=0.1,
                socket_timeout=0.1,
                socket_connect_timeout=0.1,
            )
            self._redis = aioredis.Redis(connection_pool=pool)
            self._script = self._redis.register_script(TOKEN_BUCKET_SCRIPT)
        try:
            retry_ms = await self._script(
                keys=[f"ratelimit:org:{self.config.service}:{org_id}"],
                args=[self.config.per_minute / 60, self.config.burst],
            )
        except (RedisError, OSError) as exc:
            self._paused_until = time.monotonic() + PAUSE_AFTER_REDIS_ERROR
            log.warning("org rate limit off for %ss, redis failed: %r", PAUSE_AFTER_REDIS_ERROR, exc)
            return None
        if not retry_ms:
            return None
        return max(1, math.ceil(int(retry_ms) / 1000))

    def _report(self, org_id: str, scope: Scope) -> None:
        now = time.monotonic()
        reported_at, suppressed = self._reported.get(org_id, (0.0, 0))
        if now - reported_at < REPORT_EVERY:
            self._reported[org_id] = (reported_at, suppressed + 1)
            return
        self._reported[org_id] = (now, 0)
        log.warning(
            "org rate limit exceeded mode=%s service=%s org=%s method=%s path=%s suppressed=%d",
            self.config.mode,
            self.config.service,
            org_id,
            scope.get("method"),
            scope["path"],
            suppressed,
        )


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
