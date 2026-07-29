from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from thecargo.cache import cache_aside

security = HTTPBearer()

PORTAL_AUDIENCE = "portal"
CUSTOMER_IDS_TTL = 300

_customer_resolver: Callable[[UUID], Awaitable[list]] | None = None


def set_customer_resolver(resolver: Callable[[UUID], Awaitable[list]]) -> None:
    global _customer_resolver
    _customer_resolver = resolver


def customer_ids_key(account_id: UUID) -> str:
    return f"portal:customers:{account_id}"


@dataclass(frozen=True)
class PortalToken:
    account_id: UUID
    org_id: UUID
    email: str


@dataclass(frozen=True)
class CustomerScope:
    account_id: UUID
    org_id: UUID
    email: str
    customer_ids: tuple[UUID, ...]


def _get_secret_key() -> str:
    from thecargo.dependencies._settings import get_portal_jwt_secret

    return get_portal_jwt_secret()


async def get_current_customer(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> PortalToken:
    try:
        payload = jwt.decode(
            credentials.credentials,
            _get_secret_key(),
            algorithms=["HS256"],
            audience=PORTAL_AUDIENCE,
        )
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    return PortalToken(
        account_id=UUID(payload["account_id"]),
        org_id=UUID(payload["org_id"]),
        email=payload["email"],
    )


async def resolve_customer_ids(account_id: UUID) -> tuple[UUID, ...]:
    async def loader() -> list[str]:
        if _customer_resolver is not None:
            ids = await _customer_resolver(account_id)
        else:
            from thecargo.clients.portal import PortalClient

            ids = await PortalClient().account_customers(account_id)
        return [str(i) for i in ids]

    cached = await cache_aside(customer_ids_key(account_id), loader, ttl=CUSTOMER_IDS_TTL)
    return tuple(UUID(i) for i in cached)


async def get_customer_scope(
    token: PortalToken = Depends(get_current_customer),
) -> CustomerScope:
    customer_ids = await resolve_customer_ids(token.account_id)
    if not customer_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Portal account is not linked to a customer")

    return CustomerScope(
        account_id=token.account_id,
        org_id=token.org_id,
        email=token.email,
        customer_ids=customer_ids,
    )
