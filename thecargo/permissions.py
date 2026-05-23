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
    GROUPS                   — presentational SALES/OPERATIONS/... grouping
                               shared by the admin meta endpoint and the
                               auth role-detail API.
    build_permission_groups(scopes) — render GROUPS as a tree with each
                               resource's per-action scope filled in.
"""

from typing import Final

ORG_SUPERUSER_ROLE_NAME: Final[str] = "Superuser"

ACTIONS: Final[tuple[str, ...]] = ("view", "create", "update", "delete")

SCOPES: Final[tuple[str, ...]] = ("all", "own", "team")

NO_ACCESS: Final[str] = "none"

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
    "target",
    "lead_parsing",
    "order_feedback",
    "payment_method",
    "credit_card",
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
    "toolbar_activity",
)

RESOURCE_SET: Final[frozenset[str]] = frozenset(RESOURCES)
ACTION_SET: Final[frozenset[str]] = frozenset(ACTIONS)
SCOPE_SET: Final[frozenset[str]] = frozenset(SCOPES)


def is_known(resource: str, action: str) -> bool:
    return resource in RESOURCE_SET and action in ACTION_SET


GROUPS: Final[list[dict]] = [
    {
        "title": "SALES",
        "resources": [
            {
                "key": "shipment",
                "label": "Shipments",
                "children": [
                    {"key": "lead", "label": "Leads"},
                    {"key": "quote", "label": "Quotes"},
                    {"key": "order", "label": "Orders"},
                ],
            },
            {"key": "customer", "label": "Customers"},
            {"key": "contract", "label": "Contracts"},
            {"key": "tag", "label": "Tags"},
            {
                "key": "toolbar",
                "label": "Toolbar",
                "children": [
                    {"key": "toolbar_note", "label": "Notes"},
                    {"key": "toolbar_task", "label": "Tasks"},
                    {"key": "toolbar_file", "label": "Files"},
                    {"key": "toolbar_contract", "label": "Contracts"},
                    {"key": "toolbar_sms", "label": "SMS"},
                    {"key": "toolbar_email", "label": "Email"},
                    {"key": "toolbar_payment", "label": "Payments"},
                    {"key": "toolbar_activity", "label": "Activity"},
                ],
            },
            {"key": "lead_parsing", "label": "Lead Parsing"},
            {"key": "order_feedback", "label": "Order Feedback"},
        ],
    },
    {
        "title": "OPERATIONS",
        "resources": [
            {"key": "carrier", "label": "Carriers"},
            {"key": "task", "label": "Tasks"},
            {"key": "loadboard", "label": "Loadboard"},
            {"key": "provider", "label": "Providers"},
            {"key": "automation", "label": "Automation"},
            {"key": "distribution", "label": "Distribution"},
            {"key": "shipment_reason", "label": "Shipment Reasons"},
        ],
    },
    {
        "title": "COMMUNICATION",
        "resources": [
            {"key": "notification", "label": "Notifications"},
            {"key": "template", "label": "Templates"},
            {"key": "conversation", "label": "Conversations"},
            {"key": "sip_credential", "label": "SIP Credentials"},
            {"key": "power_dialer", "label": "Power Dialer"},
        ],
    },
    {
        "title": "BILLING",
        "resources": [
            {"key": "payment_method", "label": "Payment Methods"},
            {"key": "credit_card", "label": "Credit Cards"},
        ],
    },
    {
        "title": "ANALYTICS",
        "resources": [
            {"key": "target", "label": "Targets"},
            {"key": "dashboard", "label": "Dashboard"},
            {"key": "insight", "label": "Insights"},
        ],
    },
    {
        "title": "SYSTEM",
        "resources": [
            {"key": "user", "label": "Users"},
            {"key": "team", "label": "Teams"},
            {"key": "role", "label": "Roles"},
            {"key": "company_info", "label": "Company Info"},
        ],
    },
]


def ui_resource_keys() -> set[str]:
    """Every resource key referenced anywhere in GROUPS (parents + children)."""
    keys: set[str] = set()
    for group in GROUPS:
        for resource in group["resources"]:
            keys.add(resource["key"])
            for child in resource.get("children") or []:
                keys.add(child["key"])
    return keys


def _resource_node(node: dict, scopes: dict[tuple[str, str], str]) -> dict:
    """Render one GROUPS resource node with its per-action scope filled in.

    `scopes` maps (resource, action) -> granted scope. Anything absent is
    NO_ACCESS, so a role with no row for a (resource, action) reads as `none`.
    """
    out: dict = {
        "key": node["key"],
        "label": node["label"],
        "actions": {action: scopes.get((node["key"], action), NO_ACCESS) for action in ACTIONS},
    }
    children = node.get("children")
    if children:
        out["children"] = [_resource_node(child, scopes) for child in children]
    return out


def build_permission_groups(scopes: dict[tuple[str, str], str]) -> list[dict]:
    """Render GROUPS as a section tree with each resource's scopes filled in.

    Pass a `{(resource, action): scope}` map (e.g. built from a role's granted
    permissions); the result is the Access Role matrix ready for the UI, with
    every (resource, action) the role does not grant defaulting to NO_ACCESS.
    """
    return [
        {
            "title": group["title"],
            "resources": [_resource_node(resource, scopes) for resource in group["resources"]],
        }
        for group in GROUPS
    ]


_ui_keys = ui_resource_keys()
_ghost = _ui_keys - RESOURCE_SET
assert not _ghost, f"permissions.GROUPS references non-canonical resources: {sorted(_ghost)}"
_missing = RESOURCE_SET - _ui_keys
assert not _missing, f"permissions.GROUPS missing canonical resources: {sorted(_missing)}"
