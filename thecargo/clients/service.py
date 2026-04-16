import os
from typing import Any

import httpx


class ServiceClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._secret = os.environ.get("SERVICE_SECRET_KEY", "")

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
