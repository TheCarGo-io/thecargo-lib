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

# The per-tab toolbar resources that grant the same set of CRUD actions together.
# `toolbar_activity` is intentionally excluded — it is view-only and granted on its own.
_TOOLBAR_SECTIONS: Final[tuple[str, ...]] = (
    "toolbar_note",
    "toolbar_task",
    "toolbar_file",
    "toolbar_contract",
    "toolbar_sms",
    "toolbar_email",
    "toolbar_payment",
)

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
    **{f"tag.{a}": "all" for a in ("view", "create", "update", "delete")},
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
        for r in _TOOLBAR_SECTIONS
        for a in ("view", "create", "update", "delete")
    },
    "toolbar_activity.view": "all",
}

SALES_AGENT: Final[dict[str, str]] = {
    # Sales works leads and quotes; visibility into orders is read-only.
    **{f"{r}.view": "own" for r in ("lead", "quote", "order", "customer", "task", "contract", "order_feedback")},
    **{f"{r}.create": "all" for r in ("lead", "quote", "customer", "task")},
    **{f"{r}.update": "own" for r in ("lead", "quote", "customer", "task")},
    "carrier.view": "all",
    "provider.view": "all",
    "tag.view": "all",
    "tag.create": "all",
    "notification.view": "own",
    "conversation.view": "own",
    "conversation.create": "all",
    "dashboard.view": "own",
    "goal.view": "own",
    "target.view": "own",
    "template.view": "all",
    **{
        f"{r}.{a}": ("all" if a == "create" else "own")
        for r in _TOOLBAR_SECTIONS
        for a in ("view", "create", "update", "delete")
    },
    "toolbar_activity.view": "own",
}

DISPATCHER: Final[dict[str, str]] = {
    # Operations role that moves booked orders: dispatching, carriers and loadboard.
    "shipment.view": "all",
    **{f"{r}.view": "all" for r in ("lead", "quote")},
    **{f"order.{a}": "all" for a in ("view", "create", "update")},
    "order_feedback.view": "all",
    "order_feedback.create": "all",
    "order_feedback.update": "all",
    "customer.view": "all",
    **{f"carrier.{a}": "all" for a in ("view", "create", "update")},
    **{f"provider.{a}": "all" for a in ("view", "create", "update")},
    **{f"loadboard.{a}": "all" for a in ("view", "create", "update")},
    **{f"distribution.{a}": "all" for a in ("view", "create", "update")},
    "automation.view": "all",
    "shipment_reason.view": "all",
    "shipment_reason.create": "all",
    "contract.view": "all",
    **{f"task.{a}": "all" for a in ("view", "create", "update")},
    "notification.view": "all",
    "conversation.view": "all",
    "conversation.create": "all",
    "template.view": "all",
    "tag.view": "all",
    "tag.create": "all",
    "dashboard.view": "all",
    "insight.view": "all",
    "team.view": "all",
    "company_info.view": "all",
    **{
        f"{r}.{a}": ("all" if a != "delete" else "own")
        for r in _TOOLBAR_SECTIONS
        for a in ("view", "create", "update", "delete")
    },
    "toolbar_activity.view": "all",
}

ACCOUNTANT: Final[dict[str, str]] = {
    # Billing role: full control over payment instruments, read-only on shipments.
    **{f"payment_method.{a}": "all" for a in ACTIONS},
    **{f"credit_card.{a}": "all" for a in ACTIONS},
    "shipment.view": "all",
    **{f"{r}.view": "all" for r in ("quote", "order", "customer", "contract")},
    "dashboard.view": "all",
    "insight.view": "all",
    "target.view": "all",
    "notification.view": "own",
    "company_info.view": "all",
    "toolbar_note.view": "all",
    "toolbar_file.view": "all",
    **{f"toolbar_payment.{a}": "all" for a in ACTIONS},
    "toolbar_activity.view": "all",
}

SUPPORT_AGENT: Final[dict[str, str]] = {
    # Customer-support role: lives in conversations and templates, read-only on data.
    **{f"conversation.{a}": "all" for a in ("view", "create", "update")},
    "notification.view": "all",
    "notification.create": "all",
    "template.view": "all",
    "customer.view": "all",
    "customer.update": "own",
    **{f"{r}.view": "all" for r in ("shipment", "lead", "quote", "order", "contract")},
    **{f"task.{a}": "own" for a in ("view", "update")},
    "task.create": "all",
    "tag.view": "all",
    "dashboard.view": "own",
    **{
        f"{r}.{a}": ("all" if a == "create" else "own")
        for r in _TOOLBAR_SECTIONS
        for a in ("view", "create", "update", "delete")
    },
    "toolbar_activity.view": "own",
}

TEMPLATES: Final[dict[str, dict[str, str]]] = {
    "Superuser": SUPERUSER,
    "Manager": MANAGER,
    "Sales Agent": SALES_AGENT,
    "Dispatcher": DISPATCHER,
    "Accountant": ACCOUNTANT,
    "Support Agent": SUPPORT_AGENT,
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
