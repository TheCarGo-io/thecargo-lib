from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from thecargo.events import publisher

from .service import ServiceClient

__all__ = ["CommunicationClient", "CommunicationClientError"]

EMAIL_SEND_REQUESTED_TOPIC = "email.send.requested"


class CommunicationClientError(RuntimeError):
    def __init__(self, status_code: int, detail: str, code: str | None = None):
        super().__init__(f"communication service returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.code = code


class CommunicationClient(ServiceClient):
    async def send_email_by_template(
        self,
        *,
        category: str,
        to: str | list[str],
        context: dict[str, Any] | None = None,
        organization_id: UUID | str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        attachments: list[dict] | None = None,
        from_email: str | None = None,
        shipment_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
    ) -> dict:
        payload = {
            "category": category,
            "to": [to] if isinstance(to, str) else list(to),
            "organization_id": str(organization_id) if organization_id else None,
            "context": context or {},
            "cc": cc,
            "bcc": bcc,
            "reply_to": reply_to,
            "attachments": attachments,
            "from_email": from_email,
            "shipment_id": str(shipment_id) if shipment_id else None,
            "user_id": str(user_id) if user_id else None,
        }
        # Strip nones so the FastAPI handler's defaults take over.
        payload = {k: v for k, v in payload.items() if v is not None}
        return await self._send_email(payload)

    async def send_email(
        self,
        *,
        to: str | list[str],
        organization_id: UUID | str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        attachments: list[dict] | None = None,
        from_email: str | None = None,
        context: dict[str, Any] | None = None,
        shipment_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
    ) -> dict:
        payload = {
            "to": [to] if isinstance(to, str) else list(to),
            "organization_id": str(organization_id),
            "subject": subject,
            "body": body,
            "context": context or {},
            "cc": cc,
            "bcc": bcc,
            "reply_to": reply_to,
            "attachments": attachments,
            "from_email": from_email,
            "shipment_id": str(shipment_id) if shipment_id else None,
            "user_id": str(user_id) if user_id else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return await self._send_email(payload)

    async def _send_email(self, payload: dict) -> dict:
        try:
            return await self.post("/api/internal/email/send", json=payload)
        except httpx.HTTPStatusError as exc:
            detail, code = _extract_error(exc.response)
            raise CommunicationClientError(exc.response.status_code, detail, code) from exc

    # ── RabbitMQ async path ────────────────────────────────────────

    @staticmethod
    async def send_email_by_template_async(
        *,
        category: str,
        to: str | list[str],
        context: dict[str, Any] | None = None,
        organization_id: UUID | str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        attachments: list[dict] | None = None,
        from_email: str | None = None,
        shipment_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
    ) -> None:
        payload = {
            "category": category,
            "to": [to] if isinstance(to, str) else list(to),
            "organization_id": str(organization_id) if organization_id else None,
            "context": context or {},
            "cc": cc,
            "bcc": bcc,
            "reply_to": reply_to,
            "attachments": attachments,
            "from_email": from_email,
            "shipment_id": str(shipment_id) if shipment_id else None,
            "user_id": str(user_id) if user_id else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        await publisher.publish(EMAIL_SEND_REQUESTED_TOPIC, payload)


def _extract_error(response: httpx.Response) -> tuple[str, str | None]:
    try:
        body = response.json()
    except ValueError:
        return response.text or "unknown error", None
    if isinstance(body, dict):
        detail = body.get("detail")
        if detail is None:
            return str(body), None
        return str(detail), body.get("code")
    return str(body), None
