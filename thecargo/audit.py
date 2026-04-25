"""Session-level auto-audit for ORM writes.

Any model that subclasses :class:`Auditable` produces an :class:`AuditLog`
row for every create/update/delete that passes through a SQLAlchemy
session. The row is written inside the same transaction as the business
mutation, so a rollback never leaves a phantom audit entry behind.

Bulk SQL statements (``session.execute(update(...))`` /
``session.execute(delete(...))``) bypass the ORM and therefore bypass this
listener by design — call sites that must audit such operations should
load rows and use ``session.delete`` / ``obj.field = ...`` instead.
"""

import logging
import os
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import attributes

from thecargo.context import get_audit_context
from thecargo.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

_SERVICE_NAME = os.environ.get("SERVICE_NAME")

_SENSITIVE_FIELDS = frozenset({"password_hash", "token", "secret", "api_key"})
_MAX_VALUE_LEN = 5000
_PENDING_KEY = "_thecargo_audit_pending"


class Auditable:
    """Marker mixin — subclassing opts a model into audit logging.

    Example::

        class Shipment(SoftDeleteModel, Auditable):
            __audit_resource__ = "shipment"

            def __audit_label__(self) -> str | None:
                return f"Shipment {self.code}" if self.code else None
    """

    __audit_resource__: ClassVar[str]
    __audit_ignore__: ClassVar[frozenset[str]] = frozenset({"updated_at"})

    def __audit_label__(self) -> str | None:
        return None


def _jsonify(val: Any) -> Any:
    """Coerce a Python value into something ``json.dumps`` will accept."""
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
    """Full column snapshot, skipping expired/unloaded/sensitive fields."""
    state = sa_inspect(obj)
    unloaded = state.unloaded
    ignore = obj.__audit_ignore__
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.key in unloaded or col.key in ignore or col.key in _SENSITIVE_FIELDS:
            continue
        out[col.key] = _jsonify(getattr(obj, col.key, None))
    return out


def _diff(obj: "Auditable") -> tuple[dict, dict, list[str]]:
    """Return only the columns whose value actually changed this flush."""
    ignore = obj.__audit_ignore__
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    changed: list[str] = []
    for col in obj.__table__.columns:
        if col.key in ignore or col.key in _SENSITIVE_FIELDS:
            continue
        hist = attributes.get_history(obj, col.key)
        if not hist.has_changes():
            continue
        old_val = hist.deleted[0] if hist.deleted else None
        new_val = hist.added[0] if hist.added else getattr(obj, col.key, None)
        old[col.key] = _jsonify(old_val)
        new[col.key] = _jsonify(new_val)
        changed.append(col.key)
    return old, new, changed


def _build_log(
    action: str,
    obj: "Auditable",
    old_data: dict | None,
    new_data: dict | None,
    changed: list[str] | None,
) -> AuditLog:
    ctx = get_audit_context()
    try:
        label = obj.__audit_label__()
    except Exception:
        label = None
    return AuditLog(
        organization_id=getattr(obj, "organization_id", None),
        actor_id=ctx.actor_id,
        actor_email=ctx.actor_email,
        service=_SERVICE_NAME,
        resource=obj.__audit_resource__,
        resource_id=str(obj.id) if getattr(obj, "id", None) is not None else "",
        resource_label=(label[:500] if label else None),
        action=action,
        changed_fields=changed,
        old_data=old_data,
        new_data=new_data,
        request_id=ctx.request_id,
        ip_address=ctx.ip_address,
        user_agent=(ctx.user_agent[:500] if ctx.user_agent else None),
    )


def register_audit_listeners(session_class) -> None:
    """Attach capture/write hooks to a sync ``Session`` class.

    For async workflows pass ``async_sessionmaker.sync_session_class`` — the
    sync Session is what actually dispatches flush events under the hood.
    """

    @event.listens_for(session_class, "before_flush")
    def _capture(session, flush_context, instances):
        staged: list[tuple] = session.info.setdefault(_PENDING_KEY, [])
        try:
            for obj in session.new:
                if isinstance(obj, Auditable):
                    staged.append(("create", obj, None, _snapshot(obj), None))
            for obj in session.dirty:
                if isinstance(obj, Auditable):
                    old, new, changed = _diff(obj)
                    if changed:
                        staged.append(("update", obj, old, new, changed))
            for obj in session.deleted:
                if isinstance(obj, Auditable):
                    staged.append(("delete", obj, _snapshot(obj), None, None))
        except Exception:
            logger.exception("audit capture failed; audit rows may be missing")

    @event.listens_for(session_class, "after_flush")
    def _write(session, flush_context):
        staged = session.info.pop(_PENDING_KEY, [])
        for action, obj, old_data, new_data, changed in staged:
            try:
                session.add(_build_log(action, obj, old_data, new_data, changed))
            except Exception:
                logger.exception(
                    "audit write failed: %s %s",
                    action,
                    getattr(obj, "__audit_resource__", type(obj).__name__),
                )
