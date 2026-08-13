from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from thecargo.exceptions import BadRequestException
from thecargo.models.base import SoftDeleteModel
from thecargo.utils.timezone import now_ny


class AdminRepository:

    model: type
    search_fields: tuple[str, ...] = ()
    sort_fields: tuple[str, ...] = ("created_at",)
    default_sort: str = "-created_at"


    list_options: tuple = ()


    sort_tiebreak: tuple[str, ...] = ()

    def __init__(self, db: AsyncSession):
        self.db = db


    def _base_query(self, include_deleted: bool = False) -> Select:


        query = select(self.model)
        if not include_deleted and issubclass(self.model, SoftDeleteModel):
            query = query.where(self.model.deleted_at.is_(None))
        return query

    def _apply_search(self, query: Select, q: str) -> Select:
        term = f"%{q.strip()}%"
        matches = [getattr(self.model, field).ilike(term) for field in self.search_fields]
        return query.where(or_(*matches)) if matches else query

    def _apply_sort(self, query: Select, sort: str) -> Select:
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort

        if field not in self.sort_fields:
            allowed = ", ".join(sorted(self.sort_fields))
            raise BadRequestException(
                code="INVALID_SORT",
                key="admin.invalid_sort",
                message=f"Cannot sort by '{field}'. Allowed: {allowed}",
                params={"field": field, "allowed": allowed},
            )

        column = getattr(self.model, field)
        if not descending:

            return self._apply_tiebreak(query.order_by(column.asc()), field, descending=False)


        nullable = getattr(column, "nullable", True)
        query = query.order_by(column.desc().nullslast() if nullable else column.desc())
        return self._apply_tiebreak(query, field, descending=True)

    def _apply_tiebreak(self, query: Select, sorted_field: str, *, descending: bool) -> Select:

        for name in self.sort_tiebreak:
            if name == sorted_field:
                continue
            column = getattr(self.model, name)
            if not descending:
                query = query.order_by(column.asc())
                continue
            nullable = getattr(column, "nullable", True)
            query = query.order_by(column.desc().nullslast() if nullable else column.desc())
        return query


    date_field: str | None = "created_at"

    def _apply_window(self, query: Select, date_from: date | None, date_to: date | None) -> Select:

        if self.date_field is None or not hasattr(self.model, self.date_field):


            raise TypeError(
                f"{type(self).__name__} has no date column to window on "
                f"(date_field={self.date_field!r} on {self.model.__name__})"
            )

        column = getattr(self.model, self.date_field)
        if date_from is not None:
            query = query.where(column >= date_from)
        if date_to is not None:
            query = query.where(column < date_to + timedelta(days=1))
        return query

    def build_list_query(
        self,
        *,
        q: str | None = None,
        sort: str | None = None,
        organization_id: UUID | None = None,
        include_deleted: bool = False,
        date_from: date | None = None,
        date_to: date | None = None,
        **filters: Any,
    ) -> Select:

        query = self._base_query(include_deleted)

        if organization_id is not None:
            query = query.where(self.model.organization_id == organization_id)

        if date_from is not None or date_to is not None:
            query = self._apply_window(query, date_from, date_to)

        for field, value in filters.items():
            if value is not None:
                query = query.where(getattr(self.model, field) == value)

        if q and q.strip():
            query = self._apply_search(query, q)

        if self.list_options:
            query = query.options(*self.list_options)

        return self._apply_sort(query, sort or self.default_sort)

    async def get(self, id: UUID):


        query = self._base_query(include_deleted=True).where(self.model.id == id)
        if self.list_options:
            query = query.options(*self.list_options)
        return (await self.db.execute(query)).scalar_one_or_none()


    async def create(self, **kwargs):
        obj = self.model(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj, **kwargs):
        for key, value in kwargs.items():
            setattr(obj, key, value)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj) -> None:
        if isinstance(obj, SoftDeleteModel):
            obj.deleted_at = now_ny()
        else:
            await self.db.delete(obj)
        await self.db.flush()

    async def restore(self, obj):
        
        if isinstance(obj, SoftDeleteModel):
            obj.deleted_at = None
            await self.db.flush()


            await self.db.refresh(obj)
        return obj
