from uuid import UUID

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from thecargo.models.base import ReferenceModel


class CustomerReplica(ReferenceModel):
    __tablename__ = "customer_replicas"

    organization_id: Mapped[UUID] = mapped_column(index=True)
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255))
    company_type: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50), index=True)
    secondary_phone: Mapped[str | None] = mapped_column(String(50), index=True)
    company_phone: Mapped[str | None] = mapped_column(String(50), index=True)
