from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass
class AuditContext:
    actor_id: UUID | None = None
    actor_email: str | None = None
    organization_id: UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: UUID | None = None


_audit_context: ContextVar[AuditContext] = ContextVar("audit_context", default=AuditContext())


def get_audit_context() -> AuditContext:
    return _audit_context.get()


def set_audit_context(ctx: AuditContext):
    _audit_context.set(ctx)
