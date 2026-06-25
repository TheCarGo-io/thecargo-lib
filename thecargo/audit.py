import asyncio
import logging
import os
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect

from thecargo.context import get_audit_context
from thecargo.events import publisher
from thecargo.utils.timezone import now_ny

logger = logging.getLogger(__name__)

_SERVICE_NAME = os.environ.get("SERVICE_NAME")

_SENSITIVE_EXACT = frozenset({"password_hash", "password", "token", "secret", "api_key"})
_SENSITIVE_SUFFIXES = (
    "_password",
    "_password_hash",
    "_token",
    "_secret",
    "_api_key",
)
_MAX_VALUE_LEN = 5000
_PENDING_KEY = "_thecargo_audit_pending"


def _is_sensitive(column_key: str) -> bool:
    return column_key in _SENSITIVE_EXACT or column_key.endswith(_SENSITIVE_SUFFIXES)


class Auditable:
    __audit_resource__: ClassVar[str]
    __audit_ignore__: ClassVar[frozenset[str]] = frozenset({"updated_at"})
    __audit_significant__: ClassVar[frozenset[str]] = frozenset()
    __audit_lifecycle_field__: ClassVar[str | None] = None

    def __audit_label__(self) -> str | None:
        return None

    def __audit_root__(self) -> tuple[str, str] | None:
        return None


def _jsonify(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, Decimal):
        return str(val)
    if isinstance(val, Enum):
        return val.value
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace")[:_MAX_VALUE_LEN]
    if isinstance(val, (set, frozenset)):
        return [_jsonify(v) for v in val]
    if isinstance(val, str) and len(val) > _MAX_VALUE_LEN:
        return val[:_MAX_VALUE_LEN]
    return val


def _snapshot(obj: "Auditable") -> dict[str, Any]:
    state = sa_inspect(obj)
    unloaded = state.unloaded
    ignore = obj.__audit_ignore__
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.key in unloaded or col.key in ignore or _is_sensitive(col.key):
            continue
        out[col.key] = _jsonify(getattr(obj, col.key, None))
    return out


def _values_equivalent(old: Any, new: Any) -> bool:
    if old is None and new is None:
        return True
    if old is None and new == "":
        return True
    if new is None and old == "":
        return True
    if old is None or new is None:
        return False
    if old == new:
        return True
    if isinstance(old, (datetime, date, time)) or isinstance(new, (datetime, date, time)):
        return str(old) == str(new)
    try:
        return Decimal(str(old)) == Decimal(str(new))
    except (InvalidOperation, ValueError, TypeError):
        pass
    return str(old) == str(new)


def _diff(obj: "Auditable") -> tuple[dict, dict, list[str]]:
    ignore = obj.__audit_ignore__
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    changed: list[str] = []
    state = sa_inspect(obj)
    committed = state.committed_state
    for col in obj.__table__.columns:
        if col.key in ignore or _is_sensitive(col.key):
            continue
        if col.key not in committed:
            continue
        old_val = committed[col.key]
        new_val = getattr(obj, col.key, None)
        if _values_equivalent(old_val, new_val):
            continue
        old[col.key] = _jsonify(old_val)
        new[col.key] = _jsonify(new_val)
        changed.append(col.key)
    return old, new, changed


def _user_obj(ctx) -> dict[str, Any]:
    u = ctx.user
    return {
        "id": str(u.id) if u.id is not None else None,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "type": u.type,
    }


def _resolve_org_id(explicit: Any, ctx) -> str | None:
    org = explicit if explicit is not None else ctx.organization_id
    return str(org) if org is not None else None


def _root_of(obj: "Auditable", resource: str, resource_id: str | None) -> tuple[str, str | None]:
    try:
        root = obj.__audit_root__()
    except Exception:
        root = None
    if root is not None:
        return root[0], str(root[1]) if root[1] is not None else None
    return resource, resource_id


def _significant(obj: "Auditable", changed: list[str] | None) -> list[str]:
    if not changed:
        return []
    return sorted(set(changed) & obj.__audit_significant__)


def _lifecycle(obj: "Auditable", old: dict | None, new: dict | None, changed: list[str] | None) -> dict | None:
    field = obj.__audit_lifecycle_field__
    if not field or not changed or field not in changed:
        return None
    return {
        "field": field,
        "from": (old or {}).get(field),
        "to": (new or {}).get(field),
    }


def _build_payload(
    action: str,
    obj: "Auditable",
    old_data: dict | None,
    new_data: dict | None,
    changed: list[str] | None,
) -> dict[str, Any]:
    ctx = get_audit_context()
    try:
        label = obj.__audit_label__()
    except Exception:
        label = None
    org_id = getattr(obj, "organization_id", None)
    obj_id = getattr(obj, "id", None)
    resource = obj.__audit_resource__
    resource_id = str(obj_id) if obj_id is not None else None
    root_resource, root_id = _root_of(obj, resource, resource_id)
    return {
        "audit_id": str(uuid4()),
        "service": _SERVICE_NAME or "unknown",
        "organization_id": _resolve_org_id(org_id, ctx),
        "user": _user_obj(ctx),
        "resource": resource,
        "resource_id": resource_id,
        "resource_label": (label[:500] if label else None),
        "root_resource": root_resource,
        "root_id": root_id,
        "action": action,
        "changed_fields": changed,
        "significant_fields": _significant(obj, changed),
        "lifecycle_transition": _lifecycle(obj, old_data, new_data, changed),
        "old_data": old_data,
        "new_data": new_data,
        "request_id": str(ctx.request_id) if ctx.request_id is not None else None,
        "ip_address": ctx.ip_address,
        "user_agent": (ctx.user_agent[:500] if ctx.user_agent else None),
        "created_at": now_ny().isoformat(),
    }


async def emit_audit_event(
    *,
    service: str | None = None,
    resource: str,
    resource_id: str,
    action: str,
    resource_label: str | None = None,
    organization_id: str | None = None,
    root_resource: str | None = None,
    root_id: str | None = None,
    old_data: dict | None = None,
    new_data: dict | None = None,
    changed_fields: list[str] | None = None,
    significant_fields: list[str] | None = None,
    lifecycle_transition: dict | None = None,
) -> None:
    ctx = get_audit_context()
    payload = {
        "audit_id": str(uuid4()),
        "service": service or _SERVICE_NAME or "unknown",
        "organization_id": _resolve_org_id(organization_id, ctx),
        "user": _user_obj(ctx),
        "resource": resource,
        "resource_id": resource_id,
        "resource_label": (resource_label[:500] if resource_label else None),
        "root_resource": root_resource or resource,
        "root_id": root_id or resource_id,
        "action": action,
        "changed_fields": changed_fields,
        "significant_fields": significant_fields or [],
        "lifecycle_transition": lifecycle_transition,
        "old_data": old_data,
        "new_data": new_data,
        "request_id": str(ctx.request_id) if ctx.request_id is not None else None,
        "ip_address": ctx.ip_address,
        "user_agent": (ctx.user_agent[:500] if ctx.user_agent else None),
        "created_at": now_ny().isoformat(),
    }
    await _publish_one(payload)


async def _publish_one(payload: dict[str, Any]) -> None:
    routing_key = f"audit.{payload['service']}.{payload['action']}"
    try:
        await publisher.publish(routing_key, payload)
    except Exception:
        logger.exception("audit publish failed: routing_key=%s", routing_key)


def register_audit_listeners(session_class) -> None:

    @event.listens_for(session_class, "before_flush")
    def _capture(session, flush_context, instances):
        staged: list[dict[str, Any]] = session.info.setdefault(_PENDING_KEY, [])
        try:
            for obj in session.new:
                if isinstance(obj, Auditable):
                    staged.append(_build_payload("create", obj, None, _snapshot(obj), None))
            for obj in session.dirty:
                if isinstance(obj, Auditable):
                    old, new, changed = _diff(obj)
                    if changed:
                        staged.append(_build_payload("update", obj, old, new, changed))
            for obj in session.deleted:
                if isinstance(obj, Auditable):
                    staged.append(_build_payload("delete", obj, _snapshot(obj), None, None))
        except Exception:
            logger.exception("audit capture failed; audit events may be missing")

    @event.listens_for(session_class, "after_commit")
    def _publish(session):
        staged = session.info.pop(_PENDING_KEY, [])
        if not staged:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "audit publish skipped: no running event loop (count=%d). "
                "Likely a sync session outside an ASGI request.",
                len(staged),
            )
            return
        for payload in staged:
            loop.create_task(_publish_one(payload))

    @event.listens_for(session_class, "after_rollback")
    def _drop_on_rollback(session):
        session.info.pop(_PENDING_KEY, None)
