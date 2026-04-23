from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.context import get_audit_context
from thecargo.models.base import SoftDeleteModel
from thecargo.utils.timezone import now_ny

T = TypeVar("T")


def _serialize(obj) -> dict:
    """Convert model instance to plain dict (only scalar fields)."""
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name, None)
        if val is None:
            continue
        if isinstance(val, UUID):
            result[col.name] = str(val)
        elif hasattr(val, "isoformat"):
            result[col.name] = val.isoformat()
        else:
            result[col.name] = val
    # Skip sensitive fields
    for skip in ("password_hash", "token", "secret", "api_key"):
        result.pop(skip, None)
    return result


def _diff(old: dict, new: dict) -> list[str]:
    return [k for k in new if old.get(k) != new.get(k)]


class TenantRepository:
    model: type
    soft_delete: bool = False
    audit_resource: str | None = None   # e.g. "shipment", "carrier" — None = no audit

    def __init__(self, db: AsyncSession, org_id: UUID):
        self.db = db
        self.org_id = org_id

    # ------------------------------------------------------------------ #
    # Internal audit helper
    # ------------------------------------------------------------------ #
    async def _write_audit(
        self,
        action: str,
        obj,
        old_data: dict | None = None,
        new_data: dict | None = None,
        changed_fields: list | None = None,
        resource_label: str | None = None,
    ):
        if not self.audit_resource:
            return
        try:
            from thecargo.models.audit_log import AuditLog
            ctx = get_audit_context()
            log = AuditLog(
                organization_id=self.org_id,
                actor_id=ctx.actor_id,
                actor_email=ctx.actor_email,
                resource=self.audit_resource,
                resource_id=str(obj.id),
                resource_label=resource_label or getattr(obj, "__audit_label__", None),
                action=action,
                changed_fields=changed_fields,
                old_data=old_data,
                new_data=new_data,
                ip_address=ctx.ip_address,
            )
            self.db.add(log)
        except Exception:
            pass  # Audit failure must never break the main flow

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #
    def _base_query(self) -> Select:
        query = select(self.model).where(self.model.organization_id == self.org_id)
        if self.soft_delete and issubclass(self.model, SoftDeleteModel):
            query = query.where(self.model.deleted_at.is_(None))
        return query

    async def get(self, id: UUID):
        result = await self.db.execute(self._base_query().where(self.model.id == id))
        return result.scalar_one_or_none()

    # Backward-compat alias. Prefer :meth:`get` in new code.
    get_by_id = get

    def build_query(self, order_by: Any = None, options: list | None = None) -> Select:
        query = self._base_query()
        if options:
            for opt in options:
                query = query.options(opt)
        return query.order_by(order_by if order_by is not None else self.model.created_at.desc())

    async def list(
        self,
        offset: int = 0,
        limit: int = 100,
        order_by: Any = None,
        options: list | None = None,
    ) -> tuple[list, int]:
        base = self._base_query()

        count_result = await self.db.execute(select(func.count()).select_from(base.subquery()))
        count = count_result.scalar_one()

        query = base.offset(offset).limit(limit)
        if options:
            for opt in options:
                query = query.options(opt)
        query = query.order_by(order_by if order_by is not None else self.model.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all()), count

    # ------------------------------------------------------------------ #
    # Write operations (with audit)
    # ------------------------------------------------------------------ #
    async def create(self, **kwargs):
        obj = self.model(organization_id=self.org_id, **kwargs)
        self.db.add(obj)
        await self.db.flush()
        new_data = _serialize(obj)
        await self._write_audit("create", obj, new_data=new_data)
        return obj

    async def update(self, obj, **kwargs):
        old_data = _serialize(obj)
        for key, value in kwargs.items():
            setattr(obj, key, value)
        await self.db.flush()
        new_data = _serialize(obj)
        changed = _diff(old_data, new_data)
        if changed:
            await self._write_audit(
                "update", obj,
                old_data={k: old_data[k] for k in changed if k in old_data},
                new_data={k: new_data[k] for k in changed if k in new_data},
                changed_fields=changed,
            )
        return obj

    async def delete(self, obj):
        old_data = _serialize(obj)
        if self.soft_delete and isinstance(obj, SoftDeleteModel):
            obj.deleted_at = now_ny()
            await self.db.flush()
        else:
            await self.db.delete(obj)
            await self.db.flush()
        await self._write_audit("delete", obj, old_data=old_data)
