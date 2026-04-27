"""Canonical authorization model for TheCargo.

Two distinct "superuser" concepts — never conflate them:

    users.is_superuser = True
        Platform-wide administrator. Can create organizations via
        POST /api/v1/organizations, can log into the admin dashboard
        (admin/app/admin/auth.py gates on this column), and in Requires
        bypasses per-resource permission checks (Scope=all).
        There are usually 1-3 of these for the whole platform.

    role.name == "Superuser"
        Organization-scoped administrator. Has role_permissions granting
        scope="all" on every resource WITHIN their own organization.
        One per org (created automatically by setup_org_defaults).
        Cannot create other organizations and cannot log into the admin
        dashboard unless the underlying User row also has is_superuser=True.

Helpers:
    ORG_SUPERUSER_ROLE_NAME  — the magic role name the alembic migrations
                               and org-defaults setup grant everything to.
    is_known(resource, action) — validate a (resource, action) pair.
"""

from typing import Final

ORG_SUPERUSER_ROLE_NAME: Final[str] = "Superuser"

ACTIONS: Final[tuple[str, ...]] = ("view", "create", "update", "delete")

SCOPES: Final[tuple[str, ...]] = ("all", "own", "team")

# Shipment life-cycle stages. Each stage is ALSO a permission resource
# (see RESOURCES above) so roles can grant independent scopes per stage,
# e.g. Sales Agent: lead.view=own, quote.view=own, order.view=—.
# The `shipment` resource covers cross-stage operations (analytics, import/export).
STAGES: Final[tuple[str, ...]] = ("lead", "quote", "order")
STAGE_SET: Final[frozenset[str]] = frozenset(STAGES)

# Resources that support stage_filter (kept for potential future use on
# non-stage entities like `task`). Shipment itself is handled via separate
# lead/quote/order resources, so it's NOT stage_filterable any more.
STAGE_FILTERABLE_RESOURCES: Final[frozenset[str]] = frozenset()

RESOURCES: Final[tuple[str, ...]] = (
    "shipment",
    "lead",
    "quote",
    "order",
    "customer",
    "carrier",
    "task",
    "billing",
    "notification",
    "template",
    "loadboard",
    "user",
    "team",
    "role",
    "contract",
    "automation",
    "distribution",
    "provider",
    "payroll",
    "goal",
    "target",
    "lead_parsing",
    "order_feedback",
    "merchant",
    "payment_app",
    "conversation",
    "sip_credential",
    "power_dialer",
    "company_info",
    "dashboard",
    "insight",
    "shipment_reason",
    "tag",
    "toolbar",
    "toolbar_note",
    "toolbar_task",
    "toolbar_file",
    "toolbar_contract",
    "toolbar_sms",
    "toolbar_email",
    "toolbar_payment",
)

RESOURCE_SET: Final[frozenset[str]] = frozenset(RESOURCES)
ACTION_SET: Final[frozenset[str]] = frozenset(ACTIONS)
SCOPE_SET: Final[frozenset[str]] = frozenset(SCOPES)


def is_known(resource: str, action: str) -> bool:
    return resource in RESOURCE_SET and action in ACTION_SET
