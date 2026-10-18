import asyncio
import logging
from uuid import uuid4

import jwt
import pytest
import redis
from starlette.middleware.base import BaseHTTPMiddleware

from thecargo.middleware.rate_limit import RateLimitConfig, RateLimitMiddleware

SECRET = "test-secret-key-that-is-long-enough"
SERVICE_SECRET = "service-secret"
REDIS_URL = "redis://localhost:6379/15"


def _redis_is_up() -> bool:
    try:
        return redis.Redis.from_url(REDIS_URL, socket_connect_timeout=0.2).ping()
    except redis.RedisError:
        return False


needs_redis = pytest.mark.skipif(not _redis_is_up(), reason="local redis is not running")


def _token(org_id: str | None) -> str:
    payload = {"user_id": str(uuid4()), "type": "access"}
    if org_id:
        payload["org_id"] = org_id
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _scope(path: str = "/api/v1/shipments", token: str | None = None, service_secret: str | None = None) -> dict:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if service_secret:
        headers.append((b"x-service-secret", service_secret.encode()))
    return {"type": "http", "method": "GET", "path": path, "headers": headers}


def _config(**overrides) -> RateLimitConfig:
    values = {
        "jwt_secret": SECRET,
        "service_secret": SERVICE_SECRET,
        "redis_url": REDIS_URL,
        "mode": "enforce",
        "per_minute": 60,
        "burst": 2,
        "service": f"test-{uuid4()}",
    }
    values.update(overrides)
    return RateLimitConfig(**values)


async def _app(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _call(middleware: RateLimitMiddleware, scope: dict) -> tuple[int, dict]:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b""}

    async def send(message: dict) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    start = sent[0]
    return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}


def _statuses(config: RateLimitConfig, scopes: list[dict]) -> list[int]:
    async def scenario() -> list[int]:
        middleware = RateLimitMiddleware(_app, config)
        return [(await _call(middleware, scope))[0] for scope in scopes]

    return asyncio.run(scenario())


def test_the_middleware_is_pure_asgi():
    assert not issubclass(RateLimitMiddleware, BaseHTTPMiddleware)


@needs_redis
def test_an_org_over_its_burst_gets_429_with_retry_after():
    token = _token(str(uuid4()))

    async def scenario() -> list[tuple[int, dict]]:
        middleware = RateLimitMiddleware(_app, _config())
        return [await _call(middleware, _scope(token=token)) for _ in range(3)]

    results = asyncio.run(scenario())

    assert [status for status, _ in results] == [200, 200, 429]
    assert results[2][1]["retry-after"] == "1"


@needs_redis
def test_one_busy_org_does_not_spend_another_orgs_budget():
    busy, quiet = _token(str(uuid4())), _token(str(uuid4()))

    statuses = _statuses(_config(), [_scope(token=busy)] * 5 + [_scope(token=quiet)])

    assert statuses == [200, 200, 429, 429, 429, 200]


@needs_redis
def test_each_service_keeps_its_own_budget_for_an_org():
    token = _token(str(uuid4()))

    async def scenario() -> list[int]:
        shipment = RateLimitMiddleware(_app, _config(service=f"shipment-{uuid4()}"))
        comm = RateLimitMiddleware(_app, _config(service=f"comm-{uuid4()}"))
        statuses = [(await _call(shipment, _scope(token=token)))[0] for _ in range(3)]
        statuses.append((await _call(comm, _scope(token=token)))[0])
        return statuses

    assert asyncio.run(scenario()) == [200, 200, 429, 200]


@needs_redis
def test_tokens_refill_over_time():
    token = _token(str(uuid4()))

    async def scenario() -> list[int]:
        middleware = RateLimitMiddleware(_app, _config(per_minute=6000, burst=1))
        statuses = [(await _call(middleware, _scope(token=token)))[0] for _ in range(2)]
        await asyncio.sleep(0.05)
        statuses.append((await _call(middleware, _scope(token=token)))[0])
        return statuses

    assert asyncio.run(scenario()) == [200, 429, 200]


@needs_redis
def test_shadow_mode_lets_the_request_through_and_logs_it(caplog):
    org_id = str(uuid4())
    caplog.set_level(logging.WARNING, logger="thecargo.middleware.rate_limit")

    statuses = _statuses(_config(mode="shadow"), [_scope(token=_token(org_id))] * 4)

    assert statuses == [200, 200, 200, 200]
    exceeded = [r.getMessage() for r in caplog.records if "org rate limit exceeded" in r.getMessage()]
    assert len(exceeded) == 1
    assert f"org={org_id}" in exceeded[0]
    assert "mode=shadow" in exceeded[0]


@needs_redis
def test_service_to_service_calls_are_not_counted():
    token = _token(str(uuid4()))

    statuses = _statuses(_config(), [_scope(token=token, service_secret=SERVICE_SECRET)] * 4)

    assert statuses == [200, 200, 200, 200]


@needs_redis
def test_a_wrong_service_secret_is_still_counted():
    token = _token(str(uuid4()))

    statuses = _statuses(_config(), [_scope(token=token, service_secret="guess")] * 3)

    assert statuses == [200, 200, 429]


@needs_redis
def test_health_and_metrics_are_not_counted():
    token = _token(str(uuid4()))

    statuses = _statuses(_config(), [_scope("/health", token)] * 3 + [_scope("/metrics", token)] * 3)

    assert statuses == [200] * 6


@pytest.mark.parametrize(
    "scope",
    [
        _scope(),
        _scope(token=_token(None)),
        _scope(token=jwt.encode({"org_id": str(uuid4())}, "another-secret-key-long-enough-too", algorithm="HS256")),
        {"type": "http", "method": "GET", "path": "/x", "headers": [(b"authorization", b"Basic abc")]},
    ],
)
def test_requests_without_a_valid_org_token_pass_without_redis(scope):
    statuses = _statuses(_config(redis_url="redis://127.0.0.1:1/0", burst=1), [scope] * 3)

    assert statuses == [200, 200, 200]


def test_off_mode_does_nothing():
    token = _token(str(uuid4()))

    statuses = _statuses(_config(mode="off", redis_url="redis://127.0.0.1:1/0", burst=1), [_scope(token=token)] * 3)

    assert statuses == [200, 200, 200]


def test_redis_down_fails_open_and_pauses_the_limiter(caplog):
    token = _token(str(uuid4()))
    caplog.set_level(logging.WARNING, logger="thecargo.middleware.rate_limit")

    statuses = _statuses(_config(redis_url="redis://127.0.0.1:1/0", burst=1), [_scope(token=token)] * 3)

    assert statuses == [200, 200, 200]
    failures = [r for r in caplog.records if "redis failed" in r.getMessage()]
    assert len(failures) == 1
