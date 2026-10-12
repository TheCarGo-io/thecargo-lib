import hmac
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import APIKeyHeader

from thecargo.context import ANY_COMPANY, active_company, set_active_company

service_secret_header = APIKeyHeader(name="X-Service-Secret", auto_error=False)

_service_secret: str = ""


def set_service_secret(secret: str):
    global _service_secret
    _service_secret = secret


async def verify_service_auth(secret: str | None = Depends(service_secret_header)):
    if not _service_secret or not secret or not hmac.compare_digest(secret, _service_secret):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid service secret")


COMPANY_HEADER = "X-Company-Id"
_THE_ORGANIZATION = "organization"


def company_header() -> dict[str, str]:
    company_id = active_company()
    if company_id is ANY_COMPANY:
        return {}
    return {COMPANY_HEADER: str(company_id) if company_id else _THE_ORGANIZATION}


async def company_from_header(x_company_id: str | None = Header(None, alias=COMPANY_HEADER)) -> None:
    """Let a calling service say which company it is acting for.

    Only for routers that already require the service secret: the header is taken on trust.
    """
    if not x_company_id:
        return
    if x_company_id == _THE_ORGANIZATION:
        set_active_company(None)
        return
    try:
        set_active_company(UUID(x_company_id))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid company") from exc
