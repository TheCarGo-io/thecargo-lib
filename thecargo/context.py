from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class AuditUser:
    """The acting principal behind a write, resolved from the JWT.

    ``type`` distinguishes an authenticated ``user`` from a background
    ``system`` job or ``service``-to-service call that carries no token.
    ``first_name``/``last_name`` are captured as-they-were at action
    time so a later rename never rewrites audit history; the UI builds
    both the full name and the avatar initials from them.
    """

    id: UUID | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    type: str = "system"

    @property
    def full_name(self) -> str | None:
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or None


@dataclass
class AuditContext:
    user: AuditUser = field(default_factory=AuditUser)
    organization_id: UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: UUID | None = None


_audit_context: ContextVar[AuditContext] = ContextVar("audit_context", default=AuditContext())


def get_audit_context() -> AuditContext:
    return _audit_context.get()


def set_audit_context(ctx: AuditContext):
    _audit_context.set(ctx)
