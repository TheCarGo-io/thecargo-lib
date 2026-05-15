"""Typed exceptions for the project's structured error envelope.

Every error response in the platform renders the same shape::

    {
      "code":    "PAYMENT_NOT_FOUND",     // machine-readable, frontend switches on this
      "key":     "billing.payment_not_found", // i18n key resolved by Accept-Language
      "message": "Payment not found",     // translated human text (or fallback)
      "params":  {"payment_id": "..."},   // structured context for logging / templates
      "detail":  "Payment not found",     // backward-compat alias of message (legacy clients)
    }

Handlers (``thecargo.handlers``) take any exception type - including FastAPI's
own :class:`HTTPException` and Pydantic's :class:`RequestValidationError` -
and emit this envelope. New code should ``raise <Typed>Exception(...)`` so
``code``/``key``/``params`` are populated; legacy ``raise HTTPException(...)``
still works and is converted by the handler with synthetic defaults.
"""

from __future__ import annotations

from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base for the project's typed exceptions.

    Subclasses set canonical ``code`` / ``key`` defaults and accept a
    ``params`` payload that lands in the response body. The ``message``
    falls through ``HTTPException.detail`` so any code that still
    introspects ``exc.detail`` keeps working.
    """

    def __init__(
        self,
        status_code: int,
        *,
        code: str,
        key: str,
        params: dict | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.key = key
        self.params = params or {}


class BadRequestException(AppException):
    def __init__(
        self,
        *,
        code: str = "BAD_REQUEST",
        key: str = "common.bad_request",
        message: str = "Bad request",
        params: dict | None = None,
    ) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, code=code, key=key, message=message, params=params)


class UnauthorizedException(AppException):
    def __init__(
        self,
        *,
        code: str = "UNAUTHORIZED",
        key: str = "auth.unauthorized",
        message: str = "Missing or invalid access token",
        params: dict | None = None,
    ) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, code=code, key=key, message=message, params=params)


class ForbiddenException(AppException):
    def __init__(
        self,
        *,
        code: str = "FORBIDDEN",
        key: str = "auth.forbidden",
        message: str = "Insufficient permissions",
        params: dict | None = None,
    ) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, code=code, key=key, message=message, params=params)


class NotFoundException(AppException):
    """Resource not found.

    Project convention maps a missing record to **HTTP 400**, not 404 -
    see [[feedback_status_code_400_for_missing]] for the rationale. 404
    is reserved for unknown URL paths (FastAPI's own default).
    """

    def __init__(
        self,
        *,
        code: str = "NOT_FOUND",
        key: str = "common.not_found",
        message: str = "Not found",
        params: dict | None = None,
    ) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, code=code, key=key, message=message, params=params)


class ConflictException(AppException):
    def __init__(
        self,
        *,
        code: str = "CONFLICT",
        key: str = "common.conflict",
        message: str = "Conflict",
        params: dict | None = None,
    ) -> None:
        super().__init__(status.HTTP_409_CONFLICT, code=code, key=key, message=message, params=params)


class UploadTooLargeException(AppException):
    def __init__(self, max_mb: int, *, message: str | None = None) -> None:
        super().__init__(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            code="FILE_TOO_LARGE",
            key="upload.file_too_large",
            message=message or f"File exceeds {max_mb} MB limit",
            params={"max_mb": max_mb},
        )


class UploadUnsupportedTypeException(AppException):
    def __init__(self, content_type: str, allowed: list[str] | None = None) -> None:
        super().__init__(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code="UNSUPPORTED_MEDIA_TYPE",
            key="upload.unsupported_media_type",
            message=f"Unsupported file type: {content_type}",
            params={"content_type": content_type, "allowed": allowed or []},
        )


class UpstreamUnavailableException(AppException):
    """Use when an upstream service (MinIO, Stripe, RingCentral, ...) is unreachable."""

    def __init__(self, *, service: str, message: str | None = None) -> None:
        super().__init__(
            status.HTTP_502_BAD_GATEWAY,
            code="UPSTREAM_UNAVAILABLE",
            key="common.upstream_unavailable",
            message=message or f"{service} is unavailable",
            params={"service": service},
        )
