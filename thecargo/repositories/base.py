from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.context import ANY_COMPANY, AnyCompany, CompanyRef, active_company
from thecargo.models.base import CompanyScoped, SoftDeleteModel
from thecargo.utils.timezone import utc_now

T = TypeVar("T")

__all__ = [
    "ACTIVE_COMPANY",
    "ANY_COMPANY",
    "AnyCompany",
    "CompanyRef",
    "TenantRepository",
    "company_clause",
    "company_for_new_row",
    "concrete_company",
    "in_company",
]


class _Ambient:
    def __repr__(self) -> str:
        return "ACTIVE_COMPANY"


ACTIVE_COMPANY = _Ambient()


def _resolve(company_id: "CompanyRef | _Ambient") -> CompanyRef:
    return active_company() if company_id is ACTIVE_COMPANY else company_id


def concrete_company(company_id: "CompanyRef | _Ambient" = ACTIVE_COMPANY) -> UUID | None:
    company_id = _resolve(company_id)
    return None if company_id is ANY_COMPANY else company_id


def company_for_new_row() -> UUID | None:
    return concrete_company()


def in_company(company_id: CompanyRef, row_company_id: UUID | None) -> bool:
    return company_id is ANY_COMPANY or company_id == row_company_id


def company_clause(model: type, company_id: "CompanyRef | _Ambient" = ACTIVE_COMPANY) -> ColumnElement[bool]:
    company_id = _resolve(company_id)
    if company_id is ANY_COMPANY:
        return true()
    if company_id is None:
        return model.company_id.is_(None)
    return model.company_id == company_id


class TenantRepository:
    model: type
    soft_delete: bool = False

    def __init__(self, db: AsyncSession, org_id: UUID, company_id: "CompanyRef | _Ambient" = ACTIVE_COMPANY):
        self.db = db
        self.org_id = org_id
        self.company_id = _resolve(company_id)

    @property
    def company_scoped(self) -> bool:
        return issubclass(self.model, CompanyScoped)

    def _base_query(self) -> Select:
        query = select(self.model).where(self.model.organization_id == self.org_id)
        if self.company_scoped:
            query = query.where(company_clause(self.model, self.company_id))
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
        if self.company_scoped and self.company_id is not ANY_COMPANY:
            kwargs["company_id"] = self.company_id
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
            obj.deleted_at = utc_now()
            await self.db.flush()
        else:
            await self.db.delete(obj)
            await self.db.flush()
