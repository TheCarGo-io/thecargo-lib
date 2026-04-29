"""Client for the communication service.

Use :class:`CommunicationClient` from any service that needs to send
email or SMS through the platform's centralised pipeline rather than
talking to SMTP/SendGrid directly. Routing every transactional send
through one place means we keep one rendering engine, one suppression
list, one audit trail, and one set of provider credentials to rotate.

Two transports:

* **HTTP** (sync) — :meth:`send_email_by_template` / :meth:`send_email`.
  Returns the dispatcher's result inline; raises on non-2xx. Use when
  the caller can wait for delivery (admin actions, manual sends from
  the toolbar) and wants the success/failure feedback right now.

* **RabbitMQ** (async) — :meth:`send_email_by_template_async`.
  Publishes ``email.send.requested`` to the ``thecargo.events`` topic
  exchange and returns immediately. The communication consumer renders
  and dispatches. Use for background-style sends where the caller must
  not block on email delivery — the canonical case being 2FA verify
  codes, where we want the login response to come back even if SMTP is
  having a bad minute.

The two paths converge inside communication: both end up calling the
same ``email_dispatcher.dispatch`` so template resolution, SendGrid
credential pickup, and audit happen identically.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from thecargo.events import publisher

from .service import ServiceClient

__all__ = ["CommunicationClient", "CommunicationClientError"]

EMAIL_SEND_REQUESTED_TOPIC = "email.send.requested"


class CommunicationClientError(RuntimeError):
    """Raised when the communication service rejects or fails a send."""

    def __init__(self, status_code: int, detail: str, code: str | None = None):
        super().__init__(f"communication service returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.code = code


class CommunicationClient(ServiceClient):
    """Thin wrapper around the communication service's internal API."""

    async def send_email_by_template(
        self,
        *,
        key: str,
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
        """Send an email rendered from a system or org template.

        ``key`` is the slug seeded in the templates table (e.g.
        ``verify_code``, ``payment_pa``). ``organization_id`` is required
        for org-scoped templates and recommended for system templates so
        the per-org override (if any) wins over the platform fallback.
        """
        payload = {
            "template_key": key,
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
        """Send an ad-hoc email (no stored template).

        Useful when the caller has already rendered the body or wants
        to use one-off content. Use :meth:`send_email_by_template` for
        every transactional flow with a stable identity.
        """
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
        key: str,
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
        """Fire-and-forget email request via the RabbitMQ topic exchange.

        Publishes an ``email.send.requested`` event with the same body
        the HTTP path would have sent. The communication consumer
        picks it up and dispatches. Use this when you cannot afford
        to block on SMTP — login, async automations, fan-out sends.

        No return value: the caller intentionally has no signal
        (success/failure) at publish time. The consumer logs delivery
        outcomes; subscribe a downstream service to ``email.sent`` /
        ``email.send.failed`` if you need a reaction.
        """
        payload = {
            "template_key": key,
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
    """Extract (detail, code) from a structured error response.

    Communication's exception handler returns ``{detail, code}``;
    legacy/non-structured errors fall back to text + ``None`` code.
    """
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
