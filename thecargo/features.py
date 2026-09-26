"""What a subscription can switch on.

A feature key names one capability a plan sells. Keys that map to permission
resources are enforced when auth mints a token — the role's grants are
intersected with the resources the organization's features unlock. Keys with
no resources (``recording``, ``ai``) and the ``included.*`` limits are read
where there is no token, through :func:`entitlements`.

A resource no feature mentions is never gated: brokers, admin screens and the
wallet stay exactly as the role says.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from thecargo.cache import cache_get, cache_set
from thecargo.permissions import PHONE_ORG_TYPE, RESOURCE_SET

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    resources: tuple[str, ...] = ()


FEATURES: Final[dict[str, Feature]] = {
    f.key: f
    for f in (
        Feature(
            "phone",
            "Calls and texts",
            (
                "telephony",
                "conversation",
                "phone_number",
                "sip_credential",
                "contact",
                "template",
                "tag",
                "notification",
            ),
        ),
        Feature("recording", "Call recording"),
        Feature("ai", "AI transcripts, summaries and copilot"),
        Feature("ivr", "IVR, queues and ring groups"),
        Feature("analytics", "Reports", ("analytics",)),
        Feature("campaign", "Campaigns and automations", ("campaign", "automation")),
        Feature("api", "API and webhooks"),
        Feature("power_dialer", "Power dialer", ("power_dialer",)),
        Feature("supervisor", "Listen, whisper, barge and local presence"),
    )
}

LIMITS: Final[dict[str, str]] = {
    "included.voice_minutes": "Voice minutes per user per month",
    "included.numbers": "Phone numbers per user",
    "included.ai_agent_minutes": "AI agent minutes per organization per month",
}

GATED_RESOURCES: Final[frozenset[str]] = frozenset(r for f in FEATURES.values() for r in f.resources)

_bad = GATED_RESOURCES - RESOURCE_SET
assert not _bad, f"features reference unknown permission resources: {sorted(_bad)}"


def is_known(key: str) -> bool:
    return key in FEATURES or key in LIMITS


def allowed_resources(feature_keys: set[str] | frozenset[str]) -> frozenset[str]:
    """Every resource the role may keep: ungated ones plus those the features unlock."""
    unlocked = {r for key in feature_keys if key in FEATURES for r in FEATURES[key].resources}
    return (RESOURCE_SET - GATED_RESOURCES) | unlocked


def entitlements_key(organization_id: UUID | str) -> str:
    return f"org:ent:{organization_id}"


@dataclass(frozen=True)
class Entitlements:
    plan: str
    status: str
    features: dict[str, int | None]

    @property
    def active(self) -> bool:
        return self.status in ("active", "trialing", "past_due")

    def has(self, key: str) -> bool:
        return key in self.features

    def limit(self, key: str) -> int | None:
        return self.features.get(key)


ALL_FEATURES: Final[Entitlements] = Entitlements(
    plan="broker", status="active", features={key: None for key in FEATURES}
)

NO_FEATURES: Final[Entitlements] = Entitlements(plan="unknown", status="unavailable", features={})


async def _outage_fallback(organization_id: UUID | str) -> Entitlements:
    from thecargo.clients.auth import org_type

    try:
        kind = await org_type(organization_id)
    except Exception:
        logger.exception("org type lookup failed for org %s during a billing outage", organization_id)
        return ALL_FEATURES
    return NO_FEATURES if kind == PHONE_ORG_TYPE else ALL_FEATURES


async def entitlements(organization_id: UUID | str) -> Entitlements:
    """The organization's plan, status and features — Redis first, billing as the source.

    An organization billing has no subscription for is on the implicit broker
    plan: everything, no limits. If billing cannot be reached and nothing is
    cached, a broker gets the same answer — gating it on an outage would take
    features away from a customer who never had a plan — while a phone
    organization, which only ever had what it paid for, gets nothing until
    billing answers again.
    """
    raw = await cache_get(entitlements_key(organization_id))
    if raw is None:
        from thecargo.clients.service import ServiceClient

        try:
            data = await ServiceClient(
                os.environ.get("BILLING_URL") or os.environ.get("BILLING_SERVICE_URL", "http://localhost:8002")
            ).get(f"/api/internal/subscriptions/{organization_id}/entitlements")
        except Exception:
            logger.exception("entitlements lookup failed for org %s", organization_id)
            return await _outage_fallback(organization_id)
        raw = json.dumps(data)
        await cache_set(entitlements_key(organization_id), raw, ttl=600, serialize=str)
    data = json.loads(raw)
    return Entitlements(plan=data["plan"], status=data["status"], features=data["features"])


async def has_feature(organization_id: UUID | str, key: str) -> bool:
    ent = await entitlements(organization_id)
    return ent.active and ent.has(key)
