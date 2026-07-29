from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.repositories.base import TenantRepository


class CustomerNotInScopeError(ValueError):
    def __init__(self, customer_id: UUID) -> None:
        self.customer_id = customer_id
        super().__init__(f"customer {customer_id} is not linked to this portal account")


class CustomerScopedRepository(TenantRepository):
    def __init__(self, db: AsyncSession, org_id: UUID, customer_ids: Iterable[UUID]):
        super().__init__(db, org_id)
        self.customer_ids = tuple(customer_ids)

    def _base_query(self) -> Select:
        return super()._base_query().where(self.model.customer_id.in_(self.customer_ids))

    def guard(self, customer_id: UUID) -> UUID:
        if customer_id not in self.customer_ids:
            raise CustomerNotInScopeError(customer_id)
        return customer_id

    async def create(self, **kwargs):
        customer_id = kwargs.get("customer_id")
        if customer_id is not None:
            self.guard(customer_id)
        return await super().create(**kwargs)
