import os
from uuid import UUID

from thecargo.cache import cache_aside
from thecargo.clients.service import ServiceClient
from thecargo.utils.timezone import UTC as UTC_ZONE

_TTL_SECONDS = 300


class AuthServiceClient(ServiceClient):
    def __init__(self, base_url: str | None = None):
        super().__init__(
            base_url or os.environ.get("AUTH_URL") or os.environ.get("AUTH_SERVICE_URL", "http://localhost:8000"),
        )

    async def organization(self, organization_id: UUID | str) -> dict:
        return await self.get(f"/api/internal/organizations/{organization_id}")


async def org_timezone(organization_id: UUID | str) -> str:
    """The organization's IANA timezone, cached briefly.

    This is the resolver for contexts with no request token — Celery tasks and
    event consumers. There is no fallback zone: an organization always has one,
    so a lookup failure is the caller's error to surface, not to paper over.
    """

    async def _load() -> str:
        data = await AuthServiceClient().organization(organization_id)
        tz = data.get("timezone")
        if not tz:
            raise LookupError(f"organization {organization_id} has no timezone")
        return tz

    return await cache_aside(f"org:tz:{organization_id}", _load, ttl=_TTL_SECONDS)


_sync_cache: dict[str, tuple[float, str]] = {}


def org_timezone_sync(organization_id: "UUID | str") -> str:
    """`org_timezone` for sync Celery paths — httpx sync + a small TTL cache."""
    import time as _time

    import httpx

    key = str(organization_id)
    hit = _sync_cache.get(key)
    if hit and _time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1]
    base = os.environ.get("AUTH_URL") or os.environ.get("AUTH_SERVICE_URL", "http://localhost:8000")
    resp = httpx.get(
        f"{base.rstrip('/')}/api/internal/organizations/{key}",
        headers={"X-Service-Secret": os.environ.get("SERVICE_SECRET_KEY", "")},
        timeout=5,
    )
    resp.raise_for_status()
    tz = (resp.json() or {}).get("timezone")
    if not tz:
        raise LookupError(f"organization {key} has no timezone")
    _sync_cache[key] = (_time.monotonic(), tz)
    return tz


class _OrgListCache:
    value: tuple[float, list[dict]] | None = None


async def organizations() -> list[dict]:
    """Active organizations with their timezone, briefly cached — the org-hour
    fan-out gate every business-hour Celery sweep runs behind."""
    import time as _time

    hit = _OrgListCache.value
    if hit and _time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1]
    data = await AuthServiceClient().get("/api/internal/organizations")
    _OrgListCache.value = (_time.monotonic(), data)
    return data


def organizations_sync() -> list[dict]:
    import time as _time

    import httpx

    hit = _OrgListCache.value
    if hit and _time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1]
    base = os.environ.get("AUTH_URL") or os.environ.get("AUTH_SERVICE_URL", "http://localhost:8000")
    resp = httpx.get(
        f"{base.rstrip('/')}/api/internal/organizations",
        headers={"X-Service-Secret": os.environ.get("SERVICE_SECRET_KEY", "")},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _OrgListCache.value = (_time.monotonic(), data)
    return data


def org_ids_at_local_hour(orgs: list[dict], hour: int, *, weekday: int | None = None) -> set[str]:
    """Which organizations' wall clock reads ``hour`` right now.

    The UTC beat fires every hour; each business-hour task keeps its old
    "9 AM for everyone" meaning by running only for the tenants whose own
    clock says so — DST handled by the zones themselves.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(UTC_ZONE)
    matched: set[str] = set()
    for org in orgs:
        tz_name = org.get("timezone")
        if not tz_name:
            continue
        local = now.astimezone(ZoneInfo(tz_name))
        if local.hour == hour and (weekday is None or local.weekday() == weekday):
            matched.add(str(org["id"]))
    return matched
