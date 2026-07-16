from uuid import UUID

from sqlalchemy import Boolean, String
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
    sms_deliverable: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="true")
    deliverability_reason: Mapped[str | None] = mapped_column(String(30))
