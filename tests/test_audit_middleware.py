import asyncio
import gc
import os
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import Depends, FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from thecargo.context import ANY_COMPANY, active_company, get_audit_context
from thecargo.middleware.audit import AuditMiddleware
from thecargo.middleware.cancel_on_disconnect import CancelOnDisconnectMiddleware

SECRET = "test-secret"


def _scope(path: str = "/read", headers: list[tuple[bytes, bytes]] | None = None, kind: str = "http") -> dict:
    return {
        "type": kind,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("10.0.0.9", 5000),
        "server": ("test", 80),
    }


class _Client:
    def __init__(self) -> None:
        self.inbound: asyncio.Queue[dict] = asyncio.Queue()
        self.inbound.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        self.sent: list[dict] = []

    async def receive(self) -> dict:
        return await self.inbound.get()

    async def send(self, message: dict) -> None:
        self.sent.append(message)

    def disconnect(self) -> None:
        self.inbound.put_nowait({"type": "http.disconnect"})

    def header(self, name: bytes) -> list[bytes]:
        start = next(m for m in self.sent if m["type"] == "http.response.start")
        return [v for k, v in start["headers"] if k.lower() == name]


def _seen_app(seen: dict):
    app = FastAPI()

    @app.get("/read")
    async def read():
        ctx = get_audit_context()
        seen.update(ctx=ctx, company=active_company())
        return {"ok": True}

    return app


def test_is_not_a_base_http_middleware():
    assert not issubclass(AuditMiddleware, BaseHTTPMiddleware)


def test_sets_context_from_token_and_adds_request_id():
    seen: dict = {}
    user_id, org_id = uuid4(), uuid4()
    token = jwt.encode(
        {"user_id": str(user_id), "org_id": str(org_id), "email": "a@b.c", "name": "Ada Lovelace"}, SECRET
    )
    headers = [(b"authorization", f"Bearer {token}".encode()), (b"user-agent", b"x" * 900)]
    client = _Client()

    asyncio.run(
        AuditMiddleware(_seen_app(seen), jwt_secret=SECRET)(_scope(headers=headers), client.receive, client.send)
    )

    ctx = seen["ctx"]
    assert ctx.user.id == user_id
    assert ctx.organization_id == org_id
    assert (ctx.user.first_name, ctx.user.last_name, ctx.user.type) == ("Ada", "Lovelace", "user")
    assert ctx.ip_address == "10.0.0.9"
    assert len(ctx.user_agent) == 500
    assert seen["company"] is ANY_COMPANY
    assert client.header(b"x-request-id") == [str(ctx.request_id).encode()]


def test_keeps_a_valid_incoming_request_id_and_replaces_a_bad_one():
    kept = str(uuid4())
    for incoming, expect_same in ((kept, True), ("not-a-uuid", False)):
        seen: dict = {}
        client = _Client()
        scope = _scope(headers=[(b"x-request-id", incoming.encode())])
        asyncio.run(AuditMiddleware(_seen_app(seen), jwt_secret=SECRET)(scope, client.receive, client.send))
        returned = client.header(b"x-request-id")
        assert len(returned) == 1
        assert (returned[0].decode() == incoming) is expect_same
        assert UUID(returned[0].decode()) == seen["ctx"].request_id


def test_a_bad_token_leaves_an_anonymous_context():
    seen: dict = {}
    client = _Client()
    scope = _scope(headers=[(b"authorization", b"Bearer nonsense"), (b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")])

    asyncio.run(AuditMiddleware(_seen_app(seen), jwt_secret=SECRET)(scope, client.receive, client.send))

    assert seen["ctx"].user.id is None
    assert seen["ctx"].ip_address == "1.2.3.4"


def test_non_http_scopes_pass_through_untouched():
    calls: list[str] = []

    async def app(scope, receive, send) -> None:
        calls.append(scope["type"])

    async def nothing() -> dict:
        return {}

    async def drop(message: dict) -> None:
        return None

    asyncio.run(AuditMiddleware(app, jwt_secret=SECRET)(_scope(kind="lifespan"), nothing, drop))

    assert calls == ["lifespan"]


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL (asyncpg)")
def test_cancelled_reads_return_every_connection_to_the_pool():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def scenario() -> tuple[int, int, int]:
        engine = create_async_engine(
            os.environ["TEST_DATABASE_URL"],
            pool_size=5,
            max_overflow=10,
            pool_timeout=5,
            connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
        )
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def get_db():
            async with maker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        api = FastAPI()

        @api.get("/read")
        async def read(db=Depends(get_db)):
            await db.execute(text("select pg_sleep(0.02)"))
            return {"ok": True}

        app = CancelOnDisconnectMiddleware(AuditMiddleware(api, jwt_secret=SECRET))
        gate = asyncio.Semaphore(12)
        cancelled = errors = 0

        async def one(i: int) -> None:
            nonlocal cancelled, errors
            async with gate:
                client = _Client()
                asyncio.get_running_loop().call_later((1 + i % 40) / 1000, client.disconnect)
                try:
                    await app(_scope(), client.receive, client.send)
                except Exception:
                    errors += 1
                if any(m.get("status") == 499 for m in client.sent):
                    cancelled += 1

        await asyncio.gather(*(one(i) for i in range(600)))
        await asyncio.sleep(0.5)
        gc.collect()
        await asyncio.sleep(0.2)
        leaked = engine.pool.checkedout()
        await engine.dispose()
        return leaked, cancelled, errors

    leaked, cancelled, errors = asyncio.run(scenario())

    assert cancelled > 100, "the scenario must really cancel requests mid-query"
    assert (leaked, errors) == (0, 0)
