from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.models.base import SoftDeleteModel
from thecargo.utils.timezone import now_ny

T = TypeVar("T")


class TenantRepository:
    """Thin wrapper enforcing ``organization_id`` scoping on every query.

    Audit-logging is handled centrally by :mod:`thecargo.audit` session
    listeners — subclass this repository without any audit boilerplate and
    tag the *model* with :class:`~thecargo.audit.Auditable` if you want
    writes to produce ``audit_logs`` rows.
    """

    model: type
    soft_delete: bool = False

    def __init__(self, db: AsyncSession, org_id: UUID):
        self.db = db
        self.org_id = org_id

    def _base_query(self) -> Select:
        query = select(self.model).where(self.model.organization_id == self.org_id)
        if self.soft_delete and issubclass(self.model, SoftDeleteModel):
            query = query.where(self.model.deleted_at.is_(None))
        return query

    async def get(self, id: UUID):
        result = await self.db.execute(self._base_query().where(self.model.id == id))
        return result.scalar_one_or_none()

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

    async def create(self, **kwargs):
        obj = self.model(organization_id=self.org_id, **kwargs)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, obj, **kwargs):
        for key, value in kwargs.items():
            setattr(obj, key, value)
        await self.db.flush()
        return obj

    async def delete(self, obj):
        if self.soft_delete and isinstance(obj, SoftDeleteModel):
            obj.deleted_at = now_ny()
            await self.db.flush()
        else:
            await self.db.delete(obj)
            await self.db.flush()
