from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AuditBase(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class AuditLog(AuditBase):
    """Immutable, append-only audit trail for every create/update/delete.

    Rows are written by the session-level audit listener (see
    :mod:`thecargo.audit`) inside the same transaction as the mutation they
    describe, so a rolled-back write never produces a phantom audit entry.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_org_created", "organization_id", "created_at"),
        Index("ix_audit_resource_time", "resource", "resource_id", "created_at"),
        Index("ix_audit_actor", "actor_id"),
        Index("ix_audit_request_id", "request_id"),
        Index("ix_audit_service", "service"),
        Index(
            "ix_audit_new_data_gin",
            "new_data",
            postgresql_using="gin",
            postgresql_ops={"new_data": "jsonb_path_ops"},
        ),
        CheckConstraint(
            "action IN ('create', 'update', 'delete')",
            name="audit_action_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None]

    actor_id: Mapped[UUID | None]
    actor_email: Mapped[str | None] = mapped_column(String(255))

    service: Mapped[str | None] = mapped_column(String(30))

    resource: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(100))
    resource_label: Mapped[str | None] = mapped_column(String(500))
    action: Mapped[str] = mapped_column(String(20))

    changed_fields: Mapped[list | None] = mapped_column(JSONB)
    old_data: Mapped[dict | None] = mapped_column(JSONB)
    new_data: Mapped[dict | None] = mapped_column(JSONB)

    request_id: Mapped[UUID | None]
    ip_address: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
