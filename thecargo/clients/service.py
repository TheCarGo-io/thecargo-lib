import os
from typing import Any

import httpx

from thecargo.context import get_audit_context


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
