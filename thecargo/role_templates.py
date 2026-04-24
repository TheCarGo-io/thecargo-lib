"""Default role permission templates used when bootstrapping a new organization.

Single source of truth consumed by both the auth service (sync Python, new-org flow)
and the admin service (org defaults + "reset role to template" actions).

The structure is:
    { role_name: { "resource.action": "all" | "own" | "team" } }

Any (resource, action) pair NOT listed for a role implies no access. Use
`expand_template()` to obtain the nested dict shape consumed by the legacy
auth ROLE_DEFINITIONS call sites.
"""

from typing import Final

from thecargo.permissions import ACTIONS, RESOURCES

SUPERUSER: Final[dict[str, str]] = {f"{r}.{a}": "all" for r in RESOURCES for a in ACTIONS}

MANAGER: Final[dict[str, str]] = {
    **{
        f"{r}.view": "all"
        for r in (
            "shipment",
            "lead",
            "quote",
            "order",
            "customer",
            "carrier",
            "task",
            "billing",
            "contract",
            "provider",
            "notification",
            "conversation",
            "order_feedback",
            "dashboard",
            "insight",
            "payroll",
            "goal",
            "target",
        )
    },
    **{
        f"{r}.{a}": "own"
        for r in ("shipment", "lead", "quote", "order", "customer", "task", "contract")
        for a in ("create", "update")
    },
    **{f"{r}.{a}": "all" for r in ("automation", "distribution", "template") for a in ("view", "create", "update")},
    "team.view": "all",
    "user.view": "all",
    "role.view": "all",
    "company_info.view": "all",
    "company_info.update": "all",
    "lead_parsing.view": "all",
    "lead_parsing.create": "all",
    "lead_parsing.update": "all",
    **{
        f"{r}.{a}": ("all" if a != "delete" else "own")
        for r in (
            "toolbar_note",
            "toolbar_task",
            "toolbar_file",
            "toolbar_contract",
            "toolbar_sms",
            "toolbar_email",
            "toolbar_payment",
        )
        for a in ("view", "create", "update", "delete")
    },
}

SALES_AGENT: Final[dict[str, str]] = {
    # Sales works leads and quotes; visibility into orders is read-only.
    **{f"{r}.view": "own" for r in ("lead", "quote", "order", "customer", "task", "contract", "order_feedback")},
    **{f"{r}.create": "all" for r in ("lead", "quote", "customer", "task")},
    **{f"{r}.update": "own" for r in ("lead", "quote", "customer", "task")},
    "carrier.view": "all",
    "provider.view": "all",
    "notification.view": "own",
    "conversation.view": "own",
    "conversation.create": "all",
    "dashboard.view": "own",
    "goal.view": "own",
    "target.view": "own",
    "template.view": "all",
    **{
        f"{r}.view": "own"
        for r in (
            "toolbar_note",
            "toolbar_task",
            "toolbar_file",
            "toolbar_contract",
            "toolbar_sms",
            "toolbar_email",
            "toolbar_payment",
        )
    },
    **{
        f"{r}.{a}": ("all" if a == "create" else "own")
        for r in (
            "toolbar_note",
            "toolbar_task",
            "toolbar_file",
            "toolbar_contract",
            "toolbar_sms",
            "toolbar_email",
            "toolbar_payment",
        )
        for a in ("create", "update", "delete")
    },
}

TEMPLATES: Final[dict[str, dict[str, str]]] = {
    "Superuser": SUPERUSER,
    "Manager": MANAGER,
    "Sales Agent": SALES_AGENT,
}


def expand_template(template: dict[str, str]) -> dict[str, dict[str, str | None]]:
    """Convert a flat "resource.action" → scope map into the nested shape:
        { resource: { "view": scope|None, "create": scope|None, ... } }

    Actions missing from the template become None (= no access).
    """
    nested: dict[str, dict[str, str | None]] = {r: {a: None for a in ACTIONS} for r in RESOURCES}
    for key, scope in template.items():
        resource, action = key.split(".", 1)
        if resource in nested and action in nested[resource]:
            nested[resource][action] = scope
    return nested
