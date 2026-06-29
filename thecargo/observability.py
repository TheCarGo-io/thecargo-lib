from __future__ import annotations

import asyncio
import logging
import os

_log = logging.getLogger(__name__)
_initialized = False

_CONTROL_FLOW_EXC = (KeyboardInterrupt, SystemExit, asyncio.CancelledError)


def init_sentry() -> bool:
    global _initialized
    if _initialized:
        return True

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        _log.warning("SENTRY_DSN is set but sentry-sdk is not installed; error tracking disabled")
        return False

    service = os.environ.get("SERVICE_NAME", "unknown")
    environment = os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "production"

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        server_name=service,
        release=os.environ.get("RELEASE_SHA") or None,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0.0,
        send_default_pii=False,
        max_request_body_size="small",
        before_send=_enrich_event,
    )
    _initialized = True
    _log.info("Sentry error tracking initialised (service=%s env=%s)", service, environment)
    return True


def _enrich_event(event: dict, hint: dict) -> dict | None:
    exc_info = (hint or {}).get("exc_info")
    if exc_info and isinstance(exc_info[1], _CONTROL_FLOW_EXC):
        return None

    try:
        from thecargo.context import get_audit_context

        ctx = get_audit_context()
        tags = event.setdefault("tags", {})
        tags.setdefault("service", os.environ.get("SERVICE_NAME", "unknown"))
        if ctx.organization_id:
            tags["organization_id"] = str(ctx.organization_id)
        if ctx.request_id:
            tags["request_id"] = str(ctx.request_id)
        if ctx.user and (ctx.user.id or ctx.user.email):
            user = event.setdefault("user", {})
            if ctx.user.id:
                user.setdefault("id", str(ctx.user.id))
            if ctx.user.email:
                user.setdefault("email", ctx.user.email)
    except Exception:
        pass
    return event


def capture_exception(exc: BaseException) -> None:
    if not _initialized:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        pass
