from uuid import UUID

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column


class FileMixin:
    organization_id: Mapped[UUID] = mapped_column(index=True)
    filename: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_by: Mapped[UUID | None] = mapped_column(index=True)
