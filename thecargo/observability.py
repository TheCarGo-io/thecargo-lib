from __future__ import annotations

import asyncio
import logging
import os

_log = logging.getLogger(__name__)
_initialized = False


def init_sentry() -> bool:
    global _initialized
    if _initialized:
        return True

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        _log.warning("SENTRY_DSN is set but sentry-sdk is not installed; error tracking disabled")
        return False

    integrations = []
    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        integrations.extend([StarletteIntegration(), FastApiIntegration()])
    except Exception:
        pass
    try:
        from sentry_sdk.integrations.celery import CeleryIntegration

        integrations.append(CeleryIntegration(monitor_beat_tasks=False, propagate_traces=False))
    except Exception:
        pass

    service = os.environ.get("SERVICE_NAME", "unknown")
    environment = os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "production"

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        server_name=service,
        release=os.environ.get("RELEASE_SHA") or None,
        integrations=integrations,
        traces_sample_rate=0.0,
        send_default_pii=False,
        max_request_body_size="small",
        before_send=_enrich_event,
    )
    _initialized = True
    _log.info("Sentry error tracking initialised (service=%s env=%s)", service, environment)
    return True


def _is_cancellation(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, asyncio.CancelledError):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


def _enrich_event(event: dict, hint: dict) -> dict | None:
    hint = hint or {}
    record = hint.get("log_record")
    if record is not None and not record.exc_info:
        return None

    exc_info = hint.get("exc_info") or (record.exc_info if record is not None else None)
    if exc_info and _is_cancellation(exc_info[1]):
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


def install_celery_signals() -> bool:
    try:
        from celery.signals import worker_process_init
    except ImportError:
        return False

    def _init_in_worker(**_kwargs) -> None:
        global _initialized
        _initialized = False
        init_sentry()

    worker_process_init.connect(_init_in_worker, weak=False)
    return True
