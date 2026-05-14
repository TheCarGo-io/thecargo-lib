import os
from typing import Any

import httpx


class ServiceClient:
    """HTTP client for service-to-service calls.

    Pass ``service_secret=settings.SERVICE_SECRET_KEY`` from the caller's
    Settings so the secret comes from the loaded ``.env`` (pydantic) and
    not the process environment — the latter is empty when a service is
    started via uvicorn without ``--env-file``, which previously caused
    silent 403 ``Invalid service secret`` failures downstream.

    Backward-compatible default: when ``service_secret`` is omitted, fall
    back to ``os.environ["SERVICE_SECRET_KEY"]`` (Docker/swarm passes
    env vars through to the process so the fallback works there).
    """

    def __init__(self, base_url: str, *, service_secret: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._secret = service_secret if service_secret is not None else os.environ.get("SERVICE_SECRET_KEY", "")

    def _headers(self) -> dict:
        return {"X-Service-Secret": self._secret}

    async def get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}{path}", params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, json: Any = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}{path}", json=json, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def patch(self, path: str, json: Any = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.patch(f"{self.base_url}{path}", json=json, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def delete(self, path: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.delete(f"{self.base_url}{path}", headers=self._headers())
            resp.raise_for_status()
            return resp.json()
