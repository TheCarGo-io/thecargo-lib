from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


class BaseModel(Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SoftDeleteModel(BaseModel):
    __abstract__ = True

    deleted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)


class ReferenceModel(Base):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class FieldTooLongError(ValueError):
    def __init__(self, table: str, column: str, max_length: int, actual_length: int) -> None:
        self.table = table
        self.column = column
        self.max_length = max_length
        self.actual_length = actual_length
        super().__init__(f"{table}.{column} exceeds {max_length} characters (got {actual_length})")


class NaiveDatetimeError(ValueError):
    def __init__(self, table: str, column: str) -> None:
        self.table = table
        self.column = column
        super().__init__(f"{table}.{column} was given a naive datetime; every stored instant must carry a timezone")


def _enforce_column_contracts(mapper, connection, target) -> None:
    for col in mapper.columns:
        col_type = col.type
        value = getattr(target, col.key, None)
        if isinstance(col_type, String):
            max_length = col_type.length
            if max_length is None or not isinstance(value, str):
                continue
            if len(value) > max_length:
                raise FieldTooLongError(
                    table=target.__tablename__,
                    column=col.key,
                    max_length=max_length,
                    actual_length=len(value),
                )
        elif isinstance(col_type, DateTime) and col_type.timezone:
            if isinstance(value, datetime) and value.tzinfo is None:
                raise NaiveDatetimeError(table=target.__tablename__, column=col.key)


event.listen(Base, "before_insert", _enforce_column_contracts, propagate=True)
event.listen(Base, "before_update", _enforce_column_contracts, propagate=True)
