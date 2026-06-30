from __future__ import annotations

from typing import Any, Final

from pydantic import Field

from thecargo.schemas.base import AppSchema


class ValidationErrorItem(AppSchema):
    loc: str = Field(..., description="Dotted path to the offending field", example="amount")
    code: str = Field(..., description="Machine-readable validation code", example="FIELD_REQUIRED")
    key: str = Field(..., description="i18n key for the validation message", example="validation.field_required")
    message: str = Field(..., description="Translated human-readable message", example="Field is required")
    params: dict[str, Any] = Field(default_factory=dict, description="Structured context for templating / logging")


class ErrorResponse(AppSchema):
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
    return {
        code: {
            "model": ErrorResponse,
            "description": overrides.get(f"e{code}", _DESCRIPTIONS.get(code, "Error")),
        }
        for code in codes
    }


def auth_responses(*codes: int, **overrides: str) -> dict[int, dict]:
    return standard_responses(401, 403, *codes, **overrides)


ERR_AUTH: Final = standard_responses(401, 403)
