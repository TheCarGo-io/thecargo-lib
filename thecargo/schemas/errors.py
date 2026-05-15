"""Standard error envelope + FastAPI ``responses={}`` factory.

The envelope is uniform across **every** error response in the platform -
4xx, 5xx, and validation alike - so the frontend handles a single shape::

    {
      "code":    "PAYMENT_NOT_FOUND",
      "key":     "billing.payment_not_found",
      "message": "Payment not found",
      "params":  {"payment_id": "..."},
      "detail":  "Payment not found",   # backward-compat alias of message
      "errors":  [...]                  # 422 only
    }

Routes declare ``responses=`` via :func:`standard_responses` so Swagger
shows the same schema/description for the same status code across the
project. Override a code's description with kwargs keyed ``e<code>``
(``e404="Payment not found"``).
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field

from thecargo.schemas.base import AppSchema


class ValidationErrorItem(AppSchema):
    """Per-field entry inside the ``errors`` array on a 422 response."""

    loc: str = Field(..., description="Dotted path to the offending field", example="amount")
    code: str = Field(..., description="Machine-readable validation code", example="FIELD_REQUIRED")
    key: str = Field(..., description="i18n key for the validation message", example="validation.field_required")
    message: str = Field(..., description="Translated human-readable message", example="Field is required")
    params: dict[str, Any] = Field(default_factory=dict, description="Structured context for templating / logging")


class ErrorResponse(AppSchema):
    """Uniform error envelope - every non-2xx response in the platform.

    ``detail`` is kept for backward compatibility with clients that
    consumed the old FastAPI default ``{"detail": "..."}`` shape; new
    clients should branch on ``code`` and render ``message``.
    """

    code: str = Field(..., description="Machine-readable error code", example="NOT_FOUND")
    key: str = Field(..., description="i18n key for the message", example="common.not_found")
    message: str = Field(..., description="Translated human-readable text", example="Not found")
    params: dict[str, Any] = Field(default_factory=dict, description="Structured context (template vars, IDs, limits)")
    detail: str = Field(..., description="Legacy alias of ``message`` for old clients", example="Not found")
    errors: list[ValidationErrorItem] | None = Field(
        None, description="Per-field breakdown - present only on 422 validation responses"
    )


_DESCRIPTIONS: Final[dict[int, str]] = {
    400: "Invalid request payload",
    401: "Missing or invalid access token",
    403: "Insufficient permissions",
    404: "Resource not found",
    409: "Conflicting state",
    413: "Payload too large",
    415: "Unsupported media type",
    422: "Validation error",
    429: "Too many requests",
    500: "Internal server error",
    502: "Upstream dependency unavailable",
    503: "Service unavailable",
}


def standard_responses(*codes: int, **overrides: str) -> dict[int, dict]:
    """Build a FastAPI ``responses={}`` mapping for the given status codes.

    Each code is wired to :class:`ErrorResponse` plus a canonical description
    so Swagger docs are uniform across services. Override a specific code's
    description via kwargs keyed ``e<code>`` (Python forbids bare-int kwargs,
    so we prefix with ``e``).

    Example:
        ``responses=standard_responses(401, 403, 404, e404="Payment not found")``
    """
    return {
        code: {
            "model": ErrorResponse,
            "description": overrides.get(f"e{code}", _DESCRIPTIONS.get(code, "Error")),
        }
        for code in codes
    }
