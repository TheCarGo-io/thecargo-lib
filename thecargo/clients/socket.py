from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from .service import ServiceClient

__all__ = ["SocketClient"]

logger = logging.getLogger(__name__)


class SocketClient(ServiceClient):
    def __init__(self, base_url: str, *, service_secret: str | None = None, timeout: float = 2.0):
        super().__init__(base_url, service_secret=service_secret, timeout=timeout)

    async def send(self, user_id: UUID | str, message_type: str, data: dict[str, Any]) -> bool:
        body = {"user_id": str(user_id), "message_type": message_type, "data": data}
        result = await self._safe_post("/api/send", body)
        return bool(result and result.get("success"))

    async def is_online(self, user_id: UUID | str) -> bool:
        result = await self._safe_get(f"/api/online/{user_id}")
        return bool(result and result.get("online"))

    async def kick(
        self,
        user_id: UUID | str,
        *,
        keep_sid: UUID | str | None = None,
        reason: str = "session_revoked",
    ) -> int:
        body = {
            "user_id": str(user_id),
            "keep_sid": str(keep_sid) if keep_sid else None,
            "reason": reason,
        }
        result = await self._safe_post("/api/kick", body)
        return int(result.get("closed", 0)) if result else 0

    async def _safe_get(self, path: str) -> dict | None:
        try:
            return await self.get(path)
        except Exception as exc:
            logger.warning("socket_get_failed path=%s err=%s", path, exc)
            return None

    async def _safe_post(self, path: str, body: dict) -> dict | None:
        try:
            return await self.post(path, body)
        except Exception as exc:
            logger.warning("socket_post_failed path=%s err=%s", path, exc)
            return None
