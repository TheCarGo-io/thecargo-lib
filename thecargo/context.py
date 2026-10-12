from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class AuditUser:
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


class AnyCompany:
    def __repr__(self) -> str:
        return "ANY_COMPANY"


ANY_COMPANY = AnyCompany()

CompanyRef = UUID | None | AnyCompany

_active_company: ContextVar[CompanyRef] = ContextVar("active_company", default=ANY_COMPANY)


def active_company() -> CompanyRef:
    return _active_company.get()


def set_active_company(company_id: CompanyRef) -> None:
    _active_company.set(company_id)


@contextmanager
def as_company(company_id: CompanyRef):
    token = _active_company.set(company_id)
    try:
        yield
    finally:
        _active_company.reset(token)
