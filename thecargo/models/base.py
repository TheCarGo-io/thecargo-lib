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
    """Raised when a string column receives a value longer than its declared length.

    Inherits from :class:`ValueError` so existing handlers that catch
    ``ValueError`` still work; services can register a dedicated FastAPI
    exception handler that converts this into a 422 response instead of
    letting it bubble up as a 500.
    """

    def __init__(self, table: str, column: str, max_length: int, actual_length: int) -> None:
        self.table = table
        self.column = column
        self.max_length = max_length
        self.actual_length = actual_length
        super().__init__(f"{table}.{column} exceeds {max_length} characters (got {actual_length})")


def _enforce_string_lengths(mapper, connection, target) -> None:
    """Reject inserts/updates where a String(N) column overflows its limit.

    Acts as a defense-in-depth complement to Pydantic ``max_length``: any
    writer that bypasses the HTTP layer (Celery tasks, RabbitMQ consumers,
    admin imports, alembic data migrations) still gets a clear domain error
    instead of an opaque Postgres ``StringDataRightTruncationError``.
    """
    for col in mapper.columns:
        col_type = col.type
        if not isinstance(col_type, String):
            continue
        max_length = col_type.length
        if max_length is None:
            continue
        value = getattr(target, col.key, None)
        if not isinstance(value, str):
            continue
        if len(value) > max_length:
            raise FieldTooLongError(
                table=target.__tablename__,
                column=col.key,
                max_length=max_length,
                actual_length=len(value),
            )


event.listen(Base, "before_insert", _enforce_string_lengths, propagate=True)
event.listen(Base, "before_update", _enforce_string_lengths, propagate=True)
