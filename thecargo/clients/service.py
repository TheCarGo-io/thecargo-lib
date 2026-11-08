import asyncio
import os
from typing import Any

import httpx

from thecargo.context import get_audit_context

_SSL_CONTEXT = httpx.create_ssl_context()
_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=4.0)
_shared: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None


def shared_client() -> httpx.AsyncClient:
    """The pooled client for calls between services, one per event loop.

    A client built per call loads the CA bundle into a fresh SSL context (about 9 ms of CPU), resolves DNS and opens
    a new TCP connection on every request. A Celery task runs each body under its own loop, so the client is rebuilt
    when the running loop changes rather than reusing connections bound to a closed one. Idle connections expire
    after 4 s, before uvicorn's 5 s keep-alive closes them from the server side.
    """
    global _shared
    loop = asyncio.get_running_loop()
    if _shared is None or _shared[0] is not loop or _shared[1].is_closed:
        _shared = (loop, httpx.AsyncClient(verify=_SSL_CONTEXT, limits=_LIMITS))
    return _shared[1]


class ServiceClient:
    def __init__(self, base_url: str, *, service_secret: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._secret = service_secret if service_secret is not None else os.environ.get("SERVICE_SECRET_KEY", "")

    def _headers(self) -> dict:
        """Service secret, plus the actor when the request is being made on behalf of one.

        A service acting for the AI receptionist (an inbound-call tool that goes
        shipment → communication to email a contract) carries the actor forward, so
        the downstream row is attributed to the AI and not to the calling service.
        """
        headers = {"X-Service-Secret": self._secret}
        actor = get_audit_context().user.type
        if actor == "ai":
            headers["X-Actor-Source"] = actor
        return headers

    async def get(self, path: str, params: dict | None = None) -> dict:
        resp = await shared_client().get(
            f"{self.base_url}{path}", params=params, headers=self._headers(), timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json: Any = None) -> dict:
        resp = await shared_client().post(
            f"{self.base_url}{path}", json=json, headers=self._headers(), timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    async def patch(self, path: str, json: Any = None) -> dict:
        resp = await shared_client().patch(
            f"{self.base_url}{path}", json=json, headers=self._headers(), timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    async def delete(self, path: str) -> dict:
        resp = await shared_client().delete(f"{self.base_url}{path}", headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
