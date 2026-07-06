from enum import Enum
from uuid import UUID

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from thecargo.audit import Auditable
from thecargo.db.types import USPhoneType
from thecargo.models.base import BaseModel


class ConsentChannel(str, Enum):
    CALL = "call"
    TEXT = "text"


class ConsentScope(str, Enum):
    GLOBAL = "global"
    LINE = "line"


class ConsentStatus(str, Enum):
    DO_NOT_CALL = "do_not_call"
    DO_NOT_TEXT = "do_not_text"
    WRONG_NUMBER = "wrong_number"
    ALLOWED = "allowed"


class ConsentSource(str, Enum):
    KEYWORD = "keyword"
    AGENT = "agent"
    IMPORT = "import"
    SYSTEM = "system"
    AI_AGENT = "ai_agent"


class SendType(str, Enum):
    MANUAL = "manual"
    MASS = "mass"
    AUTOMATED = "automated"


class ConsentRecord(BaseModel, Auditable):
    __tablename__ = "consent_records"
    __audit_resource__ = "consent_record"
    __audit_significant__ = frozenset({"status", "scope", "line_number"})

    __table_args__ = (
        Index(
            "ix_consent_records_lookup",
            "organization_id",
            "customer_number",
            "channel",
            "scope",
            "line_number",
            "created_at",
        ),
        Index("ix_consent_records_org_customer", "organization_id", "customer_number"),
    )

    organization_id: Mapped[UUID] = mapped_column(index=True)
    customer_number: Mapped[str] = mapped_column(USPhoneType(), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    scope: Mapped[str] = mapped_column(String(8), nullable=False)
    line_number: Mapped[str | None] = mapped_column(USPhoneType(), default=None)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_detail: Mapped[str | None] = mapped_column(Text, default=None)
    created_by_user_id: Mapped[UUID | None] = mapped_column(default=None)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
