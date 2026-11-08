import asyncio

import httpx

from thecargo.clients import service
from thecargo.clients.service import ServiceClient


def _counting_client(monkeypatch) -> list[httpx.AsyncClient]:
    built: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"path": request.url.path})

    def _build(*args, **kwargs):
        client = real(*args, transport=httpx.MockTransport(_handler), **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(service.httpx, "AsyncClient", _build)
    monkeypatch.setattr(service, "_shared", None)
    return built


def test_calls_in_one_loop_share_one_client(monkeypatch):
    built = _counting_client(monkeypatch)
    client = ServiceClient("http://svc", service_secret="s")

    async def _calls():
        assert await client.get("/a") == {"path": "/a"}
        assert await client.post("/b", json={}) == {"path": "/b"}
        assert await client.patch("/c", json={}) == {"path": "/c"}
        assert await client.delete("/d") == {"path": "/d"}

    asyncio.run(_calls())
    assert len(built) == 1


def test_a_new_event_loop_gets_its_own_client(monkeypatch):
    built = _counting_client(monkeypatch)
    client = ServiceClient("http://svc", service_secret="s")

    asyncio.run(client.get("/a"))
    asyncio.run(client.get("/a"))
    assert len(built) == 2


def test_the_caller_timeout_applies_to_each_request(monkeypatch):
    seen: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(_handler), **k)
    )
    monkeypatch.setattr(service, "_shared", None)

    asyncio.run(ServiceClient("http://svc", service_secret="s", timeout=3.0).get("/a"))
    assert seen[0]["read"] == 3.0
