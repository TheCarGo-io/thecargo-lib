from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer()

SCOPE_MAP = {"a": "all", "o": "own", "t": "team", "_": None}
ACTIONS = ["view", "create", "update", "delete"]


@dataclass(frozen=True)
class TokenPayload:
    user_id: UUID
    org_id: UUID
    role_id: UUID | None
    is_superuser: bool
    team_id: UUID | None
    permissions: dict


@dataclass(frozen=True)
class Scope:
    scope: str
    user_id: UUID
    team_id: UUID | None = None

    @property
    def is_all(self) -> bool:
        return self.scope == "all"

    @property
    def is_own(self) -> bool:
        return self.scope == "own"

    @property
    def is_team(self) -> bool:
        return self.scope == "team"


def _decode_permissions(raw: dict) -> dict:
    result = {}
    for resource_key, scope_str in raw.items():
        result[resource_key] = {
            ACTIONS[i]: SCOPE_MAP.get(ch) for i, ch in enumerate(scope_str[:4])
        }
    return result


def _get_secret_key():
    from thecargo.dependencies._settings import get_jwt_secret
    return get_jwt_secret()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    try:
        payload = jwt.decode(credentials.credentials, _get_secret_key(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    return TokenPayload(
        user_id=UUID(payload["user_id"]),
        org_id=UUID(payload["org_id"]),
        role_id=UUID(payload["role_id"]) if payload.get("role_id") else None,
        is_superuser=payload.get("is_superuser", False),
        team_id=UUID(payload["team_id"]) if payload.get("team_id") else None,
        permissions=_decode_permissions(payload.get("p", {})),
    )


async def get_org_id(user: TokenPayload = Depends(get_current_user)) -> UUID:
    return user.org_id


class Requires:
    def __init__(self, resource: str, action: str):
        self.resource = resource
        self.action = action

    async def __call__(self, user: TokenPayload = Depends(get_current_user)) -> Scope:
        if user.is_superuser:
            return Scope(scope="all", user_id=user.user_id, team_id=user.team_id)

        perm = user.permissions.get(self.resource, {})
        scope = perm.get(self.action)

        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")

        return Scope(scope=scope, user_id=user.user_id, team_id=user.team_id)
