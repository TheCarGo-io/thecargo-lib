from uuid import UUID

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from thecargo.models.base import ReferenceModel


class UserReplica(ReferenceModel):
    __tablename__ = "user_replicas"

    organization_id: Mapped[UUID] = mapped_column(index=True)
    email: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(150))
    last_name: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(50))
    ext: Mapped[str | None] = mapped_column(String(10))
    picture: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
