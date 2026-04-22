from dataclasses import dataclass, field
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
    # {resource: {action: tuple(stages) or None}}. None = no restriction (all stages).
    stage_filters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Scope:
    scope: str
    user_id: UUID
    team_id: UUID | None = None
    # Tuple of allowed stages (e.g. ("lead",)). None = no restriction / resource not stage-filterable.
    allowed_stages: tuple[str, ...] | None = None

    @property
    def is_all(self) -> bool:
        return self.scope == "all"

    @property
    def is_own(self) -> bool:
        return self.scope == "own"

    @property
    def is_team(self) -> bool:
        return self.scope == "team"

    def check_stage(self, stage: str | None) -> None:
        """Raise 403 if a specific stage is requested but not permitted by this scope.

        Call this at the top of stage-aware endpoints (e.g. list by stage, create in stage).
        When stage is None (cross-stage op) and allowed_stages is set, also raises — a
        stage-restricted role cannot perform cross-stage operations.
        """
        if self.allowed_stages is None:
            return
        if stage is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Stage-restricted role cannot perform cross-stage operation (allowed: {list(self.allowed_stages)})",
            )
        if stage not in self.allowed_stages:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Stage '{stage}' not permitted by this role (allowed: {list(self.allowed_stages)})",
            )


def _decode_permissions(raw: dict) -> dict:
    result = {}
    for resource_key, scope_str in raw.items():
        result[resource_key] = {ACTIONS[i]: SCOPE_MAP.get(ch) for i, ch in enumerate(scope_str[:4])}
    return result


def _decode_stage_filters(raw: dict) -> dict:
    """Convert JWT "ps" payload into {resource: {action: tuple(stages) or None}}."""
    result: dict = {}
    for resource, actions in (raw or {}).items():
        result[resource] = {}
        for action, stages in (actions or {}).items():
            result[resource][action] = tuple(stages) if stages else None
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
        stage_filters=_decode_stage_filters(payload.get("ps", {})),
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

        allowed_stages = user.stage_filters.get(self.resource, {}).get(self.action)

        return Scope(
            scope=scope,
            user_id=user.user_id,
            team_id=user.team_id,
            allowed_stages=allowed_stages,
        )


def check_stage_permission(user: TokenPayload, stage: str, action: str) -> Scope:
    """Resolve scope for a shipment operation on a specific stage.

    Maps stage → resource (lead | quote | order) and returns the Scope, raising
    403 if the user lacks permission. Use this in shipment endpoints that need
    stage-aware authorization (list, create, update, delete, convert).

    Platform superusers bypass all checks.
    """
    if user.is_superuser:
        return Scope(scope="all", user_id=user.user_id, team_id=user.team_id)

    if stage not in ("lead", "quote", "order"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid stage '{stage}'")

    perm = user.permissions.get(stage, {})
    scope = perm.get(action)

    if scope is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"No '{action}' permission for stage '{stage}'",
        )

    return Scope(scope=scope, user_id=user.user_id, team_id=user.team_id)
