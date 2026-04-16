from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, JSON, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AuditBase(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class AuditLog(AuditBase):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_org_created", "organization_id", "created_at"),
        Index("ix_audit_resource", "resource", "resource_id"),
        Index("ix_audit_actor", "actor_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None]

    # Kim bajardi
    actor_id: Mapped[UUID | None]
    actor_email: Mapped[str | None] = mapped_column(String(255))

    # Nima bo'ldi
    resource: Mapped[str] = mapped_column(String(100))       # "shipment", "carrier"
    resource_id: Mapped[str] = mapped_column(String(100))    # UUID as str
    resource_label: Mapped[str | None] = mapped_column(String(255))  # "Order #1234"
    action: Mapped[str] = mapped_column(String(20))          # create | update | delete

    # O'zgarish
    changed_fields: Mapped[list | None] = mapped_column(JSON)
    old_data: Mapped[dict | None] = mapped_column(JSON)
    new_data: Mapped[dict | None] = mapped_column(JSON)

    # Context
    ip_address: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
