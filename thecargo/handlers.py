from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from thecargo.exceptions import AppException
from thecargo.i18n import bind_locale_dir, get_language, translate
from thecargo.observability import capture_exception as _sentry_capture
from thecargo.observability import init_sentry

_log = logging.getLogger(__name__)

_MIRRORED_UPSTREAM_STATUSES = frozenset({400, 409, 422})


def _envelope(code: str, key: str, lang: str, params: dict | None, fallback: str) -> dict:
    params = params or {}
    message = translate(key, lang, params) or fallback
    return {
        "code": code,
        "key": key,
        "message": message,
        "params": params,
        "detail": message,
    }


def _classify_validation_error(msg: str, typ: str, loc: str, ctx: dict) -> tuple[str, str, dict]:
    if msg in ("Field required", "Missing required field"):
        return "FIELD_REQUIRED", "validation.field_required", {"field": loc}
    lower = msg.lower()
    if "valid email" in lower:
        return "EMAIL_INVALID", "validation.email_invalid", {"field": loc}
    if "min_length" in typ:
        return "MIN_LENGTH", "validation.min_length", {"field": loc, "min": ctx.get("min_length")}
    if "max_length" in typ:
        return "MAX_LENGTH", "validation.max_length", {"field": loc, "max": ctx.get("max_length")}
    if "Value error" in msg:
        reason = msg.split("Value error, ")[-1] if "Value error, " in msg else msg
        return "VALUE_ERROR", "validation.value_error", {"field": loc, "reason": reason}
    if "pattern" in typ:
        return "PATTERN_MISMATCH", "validation.pattern_mismatch", {"field": loc}
    if "greater_than" in typ:
        return "TOO_SMALL", "validation.too_small", {"field": loc, "limit": ctx.get("gt")}
    if "less_than" in typ:
        return "TOO_LARGE", "validation.too_large", {"field": loc, "limit": ctx.get("lt")}
    return "INVALID", "validation.invalid_value", {"field": loc, "reason": msg}


def _format_validation_errors(exc: RequestValidationError, lang: str) -> list[dict]:
    items = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", []) if x != "body")
        code, key, params = _classify_validation_error(
            err.get("msg", ""),
            err.get("type", "value_error"),
            loc,
            err.get("ctx") or {},
        )
        items.append(
            {
                "loc": loc,
                "code": code,
                "key": key,
                "message": translate(key, lang, params) or err.get("msg", "Invalid"),
                "params": params,
            }
        )
    return items


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    lang = get_language(request)
    envelope = _envelope(
        "VALIDATION_ERROR",
        "validation.multiple_errors",
        lang,
        {},
        "Validation failed",
    )
    envelope["errors"] = _format_validation_errors(exc, lang)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=envelope)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    lang = get_language(request)
    fallback = exc.detail if isinstance(exc.detail, str) else exc.key
    envelope = _envelope(exc.code, exc.key, lang, exc.params, fallback)
    return JSONResponse(status_code=exc.status_code, content=envelope)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    lang = get_language(request)
    code = f"HTTP_{exc.status_code}"
    key = f"common.http_{exc.status_code}"
    if isinstance(exc.detail, dict):
        detail = exc.detail
        fallback = detail.get("detail") or detail.get("message") or detail.get("error") or "Error"
        params = {k: v for k, v in detail.items() if k not in ("detail", "message", "error")}
    else:
        fallback = exc.detail if isinstance(exc.detail, str) else "Error"
        params = {}
    envelope = _envelope(code, key, lang, params, fallback)
    return JSONResponse(status_code=exc.status_code, content=envelope)


def _upstream_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500] or "Upstream request failed"
    if isinstance(body, dict):
        for field in ("message", "detail", "error"):
            value = body.get(field)
            if isinstance(value, str) and value:
                return value
    return str(body)[:500]


def _upstream_target(exc: httpx.HTTPError) -> str:
    try:
        return exc.request.url.host
    except RuntimeError:
        return "upstream"


async def upstream_exception_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
    lang = get_language(request)
    response = getattr(exc, "response", None)
    upstream_status = response.status_code if response is not None else None

    if upstream_status in _MIRRORED_UPSTREAM_STATUSES:
        envelope = _envelope(
            f"HTTP_{upstream_status}",
            f"common.http_{upstream_status}",
            lang,
            {},
            _upstream_detail(response),
        )
        return JSONResponse(status_code=upstream_status, content=envelope)

    _sentry_capture(exc)
    _log.error("Upstream call from %s %s failed: %s", request.method, request.url.path, exc)
    envelope = _envelope(
        "UPSTREAM_UNAVAILABLE",
        "common.upstream_unavailable",
        lang,
        {"service": _upstream_target(exc)},
        "Upstream service is unavailable",
    )
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=envelope)


async def fallback_handler(request: Request, exc: Exception) -> JSONResponse:
    _sentry_capture(exc)
    _log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    lang = get_language(request)
    envelope = _envelope(
        "INTERNAL_ERROR",
        "common.internal_error",
        lang,
        {},
        "Internal server error",
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope)


def register_handlers(app: FastAPI, locale_dir: Path | str | None = None) -> None:
    init_sentry()
    if locale_dir is not None:
        bind_locale_dir(locale_dir)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(httpx.HTTPError, upstream_exception_handler)
    app.add_exception_handler(Exception, fallback_handler)
