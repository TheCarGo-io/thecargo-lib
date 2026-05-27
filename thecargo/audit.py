"""Session-level auto-audit for ORM writes.

Any model that subclasses :class:`Auditable` produces an audit event
for every create/update/delete that passes through a SQLAlchemy
session. Events are *published* to RabbitMQ (``audit.{service}.{action}``
on the ``thecargo.events`` topic exchange) for the dedicated audit
service to consume and store in MongoDB.

Publish timing is ``after_commit`` — a rolled-back transaction never
emits an audit event, so audit history stays consistent with the
data that actually landed in the database. The publish itself is
fire-and-forget via ``asyncio.create_task``: if RabbitMQ is briefly
unreachable the event is logged and dropped (acceptable for the
current test phase; production should add a transactional outbox).

Bulk SQL statements (``session.execute(update(...))`` /
``session.execute(delete(...))``) bypass the ORM and therefore bypass
this listener by design — call sites that must audit such operations
should load rows and use ``session.delete`` / ``obj.field = ...``
instead.
"""

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
    """Return True if a column should be redacted from audit snapshots.

    Matches both the curated exact-name list and a suffix list so
    namespaced credentials (``client_secret``, ``cd_client_secret``,
    ``stripe_api_key`` …) are caught without each model author
    having to opt in. Add new patterns here, never per-model — audit
    redaction is one of those things you want enforced centrally.
    """
    return column_key in _SENSITIVE_EXACT or column_key.endswith(_SENSITIVE_SUFFIXES)


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
    __audit_significant__: ClassVar[frozenset[str]] = frozenset()
    __audit_lifecycle_field__: ClassVar[str | None] = None

    def __audit_label__(self) -> str | None:
        return None

    def __audit_root__(self) -> tuple[str, str] | None:
        """Aggregate root this entity belongs to, as ``(resource, id)``.

        Powers the per-aggregate timeline: a shipment's History view
        must surface edits to the shipment *and* its child rows (stops,
        vehicles, toolbar notes/tasks/files), which are separate audit
        resources with their own ids. Each child declares its owning
        shipment here so the timeline query can pull the whole story
        with one indexed ``(root_resource, root_id)`` lookup instead of
        joining across services.

        Returning ``None`` means the entity *is* its own root (the
        shipment row itself, a standalone customer, …) and the builder
        falls back to ``(resource, id)``. The id is read from an
        already-loaded FK column so this never triggers lazy IO inside
        the flush.
        """
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
        if col.key in unloaded or col.key in ignore or _is_sensitive(col.key):
            continue
        out[col.key] = _jsonify(getattr(obj, col.key, None))
    return out


def _values_equivalent(old: Any, new: Any) -> bool:
    """Treat type-mismatched but semantically-equal values as the same.

    SQLAlchemy marks an attribute dirty the moment any assignment
    happens — the API layer commonly hands the ORM a string ("4200.00")
    where the DB stored a ``Decimal('4200.00')``, and a plain ``==``
    rejects them as different. Without this normalisation the audit
    feed fills with no-op ``changed_fields`` entries that confuse the
    forensic / compliance use case the table exists for. Money-like
    pairs round-trip through :class:`Decimal`, datetime/date/time
    pairs through ``str()``, and everything else falls back to a
    string compare so the helper never raises on exotic types.
    """
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
    """Return only the columns whose value actually changed this flush.

    Combines :meth:`InstanceState.committed_state` (SQLAlchemy's
    canonical "loaded value before the current mutation") with
    :func:`_values_equivalent` so an assignment that doesn't actually
    change the underlying value never lands in ``changed_fields``.
    The bare ``attributes.get_history(...).has_changes()`` reports
    "dirty" for every set call regardless of equality and produces
    the no-op rows where every diff entry has ``old == new``.
    """
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
    """The acting principal as a nested object on the event.

    Denormalised at write time from the JWT-derived context so the
    read path never has to call the auth service to render "who did
    this". ``type`` is ``user`` for an authenticated request, falling
    back to ``system`` for background jobs / service-to-service writes
    that carry no token. ``first_name``/``last_name`` are captured
    as-they-were so renaming a user later doesn't rewrite history.
    """
    u = ctx.user
    return {
        "id": str(u.id) if u.id is not None else None,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "type": u.type,
    }


def _root_of(obj: "Auditable", resource: str, resource_id: str | None) -> tuple[str, str | None]:
    """Resolve the aggregate-root key, falling back to the entity itself."""
    try:
        root = obj.__audit_root__()
    except Exception:
        root = None
    if root is not None:
        return root[0], str(root[1]) if root[1] is not None else None
    return resource, resource_id


def _significant(obj: "Auditable", changed: list[str] | None) -> list[str]:
    """Subset of changed columns the model flags business-critical."""
    if not changed:
        return []
    return sorted(set(changed) & obj.__audit_significant__)


def _lifecycle(obj: "Auditable", old: dict | None, new: dict | None, changed: list[str] | None) -> dict | None:
    """Status/stage transition extracted from an ordinary update.

    Lets the UI render a lifecycle move ("moved to Posted") distinctly
    from a field edit without inventing a new stored event type — it
    stays an ``update``, just annotated.
    """
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
    """Compose the JSON-safe envelope the audit service consumes.

    The shape is the canonical audit document Mongo will store —
    consumer is a thin pass-through, so getting the field set right
    here keeps the read API stable. ``audit_id`` is minted as a UUID
    so the consumer's unique index can dedup retried deliveries
    without losing the source row's identity.
    """
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
        "organization_id": str(org_id) if org_id is not None else None,
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
    """Publish an audit event from a non-ORM call site.

    The :class:`Auditable` mixin covers ORM writes, but a handful of
    admin/back-office endpoints mutate state through raw SQL or
    cross-service RPC and still need an audit row. Call this from
    those sites to emit the same envelope the ORM listener produces;
    the audit service has no idea (or care) that the publisher path
    differs.

    All identifying fields default to ``None`` so the caller passes
    only what's meaningful for that particular write — a permission
    flip, for instance, has no ``old_data``/``new_data`` snapshot the
    way an ORM update does, just a ``changed_fields`` list.
    """
    ctx = get_audit_context()
    payload = {
        "audit_id": str(uuid4()),
        "service": service or _SERVICE_NAME or "unknown",
        "organization_id": organization_id,
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
    """Publish one audit event to RabbitMQ — invoked as a background task.

    Failures are logged and swallowed so a broker hiccup never
    propagates as an unhandled task exception (which would clutter
    logs with ``Task exception was never retrieved`` warnings).
    """
    routing_key = f"audit.{payload['service']}.{payload['action']}"
    try:
        await publisher.publish(routing_key, payload)
    except Exception:
        logger.exception("audit publish failed: routing_key=%s", routing_key)


def register_audit_listeners(session_class) -> None:
    """Attach capture/publish hooks to a sync ``Session`` class.

    Two-phase listener pattern:

    * ``before_flush`` — capture each Auditable mutation while
      ``committed_state`` still holds the pre-mutation values that
      :func:`_diff` needs. The payload is staged in ``session.info``,
      not in any persistent store, so a rolled-back flush leaves
      nothing behind.
    * ``after_commit`` — drain the staged payloads and schedule a
      publish task per event. Running on commit (not flush) means
      a rolled-back transaction never emits a phantom audit, which
      is the whole point of pairing audit with the data write.

    For async workflows pass ``async_sessionmaker.sync_session_class``
    — the sync Session is what actually dispatches flush/commit events
    under the hood.
    """

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
