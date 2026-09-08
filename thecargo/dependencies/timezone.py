from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, status

from thecargo.dependencies.auth import TokenPayload, get_current_user


def _zone_or_stale(name: str | None) -> ZoneInfo:
    if not name:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token_stale")
    try:
        return ZoneInfo(name)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token_stale")


def token_tz(user: TokenPayload) -> ZoneInfo:
    """The viewer's effective zone (their own, or the organization's).

    Minted into the token, so a token without the claim predates the timezone
    rollout — refreshing it is the fix, hence 401 over a silent fallback.
    """
    return _zone_or_stale(user.tz)


def token_org_tz(user: TokenPayload) -> ZoneInfo:
    """The organization's zone — for windows every teammate must cut alike."""
    return _zone_or_stale(user.otz or user.tz)


async def viewer_zone(user: TokenPayload) -> ZoneInfo:
    """`token_tz` with a lookup fallback for tokens minted without the claim —
    synthetic service tokens and sessions predating the rollout."""
    if user.tz:
        return ZoneInfo(user.tz)
    from thecargo.clients.auth import org_timezone

    return ZoneInfo(await org_timezone(user.org_id))


async def org_zone(user: TokenPayload) -> ZoneInfo:
    if user.otz or user.tz:
        return ZoneInfo(user.otz or user.tz)
    from thecargo.clients.auth import org_timezone

    return ZoneInfo(await org_timezone(user.org_id))


async def get_effective_tz(user: TokenPayload = Depends(get_current_user)) -> ZoneInfo:
    return token_tz(user)


EffectiveTz = Annotated[ZoneInfo, Depends(get_effective_tz)]
