"""Variable catalogue exposed to template authors.

Single contract between the renderer (which expects a particular
nested context shape) and the UI (which lists available placeholders
for the org admin). Add a variable here and it appears in the picker,
in autocomplete, in validation, and in sample previews — no other
file needs to change.

Naming convention
-----------------
- Top-level keys are domain entities: ``customer``, ``shipment``,
  ``pickup``, ``delivery``, ``carrier``, ``agent``, ``org``.
- Lists use plural names: ``vehicles``.
- Scalar leaves use ``snake_case``.
- Snippets (multi-token Liquid blocks) live alongside scalars but
  carry an explicit ``insert`` payload.

Adding a new field
------------------
1. Add a ``FieldDef`` to the appropriate ``ObjectSchema``.
2. Add a top-level ``Variable`` referencing that path.
3. Update the corresponding serializer in
   ``shipment/app/services/v1/template_context.py`` so the builder
   populates the new key for real shipments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

VERSION = 2


class VarType(str, Enum):
    SCALAR = "scalar"
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True)
class FieldDef:
    """A leaf placeholder inside an :class:`ObjectSchema`."""

    key: str
    label: str
    sample: object | None = None
    formatter: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ObjectSchema:
    """Schema for an entity (Customer, Vehicle, Stop, …).

    Used both for documentation and to drive nested submenus when the
    user clicks an OBJECT/ARRAY variable in the picker.
    """

    name: str
    label: str
    fields: tuple[FieldDef, ...]


@dataclass(frozen=True)
class Variable:
    """A top-level placeholder the user can insert directly.

    ``path`` is the dot-path used in templates (``customer.full_name``).
    For OBJECT/ARRAY variables ``object_schema`` references a
    :class:`ObjectSchema` from :data:`SCHEMAS` so the UI can drill in.
    ``insert`` lets snippet entries override what gets dropped into the
    editor — handy for prebuilt loops over arrays.
    """

    path: str
    label: str
    group: str
    type: VarType = VarType.SCALAR
    subgroup: str | None = None
    object_schema: str | None = None
    sample: object | None = None
    formatter: str | None = None
    description: str | None = None
    insert: str | None = None


# ── Object schemas ───────────────────────────────────────────────────


CUSTOMER_SCHEMA = ObjectSchema(
    name="Customer",
    label="Customer",
    fields=(
        FieldDef("first_name", "First name", "John"),
        FieldDef("last_name", "Last name", "Mitchell"),
        FieldDef("full_name", "Full name", "John Mitchell"),
        FieldDef("email", "Email", "john@example.com"),
        FieldDef("phone", "Phone", "(555) 123-4567", formatter="phone"),
        FieldDef("alt_phone", "Alt. phone", "(555) 555-7788", formatter="phone"),
        FieldDef("company", "Company", "Mitchell Logistics LLC"),
        FieldDef("type", "Type", "business"),
        FieldDef("address", "Billing address", "123 Main St"),
        FieldDef("city", "Billing city", "Houston"),
        FieldDef("state", "Billing state", "TX"),
        FieldDef("zip", "Billing ZIP", "77006"),
    ),
)

AGENT_SCHEMA = ObjectSchema(
    name="Agent",
    label="Agent (sales rep)",
    fields=(
        FieldDef("name", "Full name", "Jane Doe"),
        FieldDef("first_name", "First name", "Jane"),
        FieldDef("last_name", "Last name", "Doe"),
        FieldDef("email", "Email", "jane@thecargo.io"),
        FieldDef("phone", "Phone", "(973) 234-1234", formatter="phone"),
    ),
)

ORG_SCHEMA = ObjectSchema(
    name="Org",
    label="Sender (your company)",
    fields=(
        FieldDef("name", "Company name", "TheCargo Inc"),
        FieldDef("email", "Company email", "support@thecargo.io"),
        FieldDef("phone", "Company phone", "(800) 555-0199", formatter="phone"),
        FieldDef("website", "Website", "https://thecargo.io"),
    ),
)

CARRIER_SCHEMA = ObjectSchema(
    name="Carrier",
    label="Carrier",
    fields=(
        FieldDef("name", "Name", "Reliable Trucking"),
        FieldDef("mc_number", "MC number", "MC-123456"),
        FieldDef("usdot", "USDOT", "USDOT-789012"),
        FieldDef("contact_name", "Contact name", "Mike Reed"),
        FieldDef("phone", "Phone", "(832) 555-1212", formatter="phone"),
        FieldDef("email", "Email", "ops@reliabletrucking.com"),
        FieldDef("city", "City", "Dallas"),
        FieldDef("state", "State", "TX"),
    ),
)

STOP_SCHEMA = ObjectSchema(
    name="Stop",
    label="Stop",
    fields=(
        FieldDef("type", "Type", "pickup"),
        FieldDef("city", "City", "Houston"),
        FieldDef("state", "State", "TX"),
        FieldDef("zip", "ZIP", "77006"),
        FieldDef("address", "Address", "1200 Main St"),
        FieldDef("business_name", "Business name", "Houston Auto Auction"),
        FieldDef("contact_name", "Contact name", "Mike Reed"),
        FieldDef("contact_phone", "Contact phone", "(832) 555-1212", formatter="phone"),
        FieldDef("scheduled_at", "Scheduled at", "2026-04-26T08:00:00", formatter="datetime_short"),
    ),
)

VEHICLE_SCHEMA = ObjectSchema(
    name="Vehicle",
    label="Vehicle",
    fields=(
        FieldDef("year", "Year", 2020),
        FieldDef("make", "Make", "Toyota"),
        FieldDef("model", "Model", "Camry"),
        FieldDef("type", "Type", "sedan"),
        FieldDef("color", "Color", "Blue"),
        FieldDef("vin", "VIN", "1HGCM82633A004352"),
        FieldDef("plate", "Plate", "ABC-1234"),
        FieldDef("lot", "Lot #", "L-99887"),
        FieldDef("is_inoperable", "Inoperable", False),
    ),
)

SHIPMENT_SCHEMA = ObjectSchema(
    name="Shipment",
    label="Shipment",
    fields=(
        FieldDef("code", "Code", "ORD-1234"),
        FieldDef("stage", "Stage", "order"),
        FieldDef("status", "Status", "dispatched", formatter="status_label"),
        FieldDef("transport_type", "Transport type", "open"),
        FieldDef("instructions", "Instructions", "Call before arrival"),
        FieldDef("first_available_date", "First available", "2026-04-25", formatter="date_short"),
        FieldDef("estimated_pickup_at", "Est. pickup", "2026-04-26T08:00:00", formatter="datetime_short"),
        FieldDef("estimated_delivery_at", "Est. delivery", "2026-04-29T16:00:00", formatter="datetime_short"),
        FieldDef("created_at", "Created at", "2026-04-20T10:00:00", formatter="date_short"),
    ),
)

PRICING_SCHEMA = ObjectSchema(
    name="Pricing",
    label="Pricing",
    fields=(
        FieldDef("tariff", "Tariff (total)", "1250.00", formatter="currency"),
        FieldDef("deposit", "Deposit", "100.00", formatter="currency"),
        FieldDef("balance_due", "Balance due", "1150.00", formatter="currency"),
        FieldDef("carrier_pay", "Carrier pay", "1000.00", formatter="currency"),
        FieldDef("cod_amount", "COD amount", "150.00", formatter="currency"),
        FieldDef("payment_method", "Payment method", "card"),
        FieldDef("payment_terms", "Payment terms", "cod"),
    ),
)


SCHEMAS: dict[str, ObjectSchema] = {
    s.name: s
    for s in (
        CUSTOMER_SCHEMA,
        AGENT_SCHEMA,
        ORG_SCHEMA,
        CARRIER_SCHEMA,
        STOP_SCHEMA,
        VEHICLE_SCHEMA,
        SHIPMENT_SCHEMA,
        PRICING_SCHEMA,
    )
}


# ── Top-level variable registry ──────────────────────────────────────


def _expand(prefix: str, schema_name: str, group: str, subgroup: str | None = None) -> tuple[Variable, ...]:
    """Generate scalar Variables for every field in an ObjectSchema."""
    schema = SCHEMAS[schema_name]
    return tuple(
        Variable(
            path=f"{prefix}.{f.key}",
            label=f.label,
            group=group,
            subgroup=subgroup,
            sample=f.sample,
            formatter=f.formatter,
            description=f.description,
        )
        for f in schema.fields
    )


REGISTRY: tuple[Variable, ...] = (
    *_expand("customer", "Customer", group="Customer"),
    *_expand("shipment", "Shipment", group="Shipment"),
    *_expand("pickup", "Stop", group="Pickup"),
    *_expand("delivery", "Stop", group="Delivery"),
    Variable(
        path="vehicles_inline",
        label="Vehicle list (inline)",
        group="Vehicles",
        type=VarType.SCALAR,
        sample="2020 Toyota Camry, 2018 Honda Civic",
        insert=(
            "{% for v in vehicles %}{{ v.year }} {{ v.make }} {{ v.model }}"
            "{% unless forloop.last %}, {% endunless %}{% endfor %}"
        ),
        description="All vehicles, comma-separated on one line.",
    ),
    Variable(
        path="vehicles_bullets",
        label="Vehicle list (bullets)",
        group="Vehicles",
        type=VarType.SCALAR,
        sample="• 2020 Toyota Camry\n• 2018 Honda Civic",
        insert=(
            "{% for v in vehicles %}- {{ v.year }} {{ v.make }} {{ v.model }}"
            "{% if v.is_inoperable %} (INOP){% endif %}\n{% endfor %}"
        ),
        description="All vehicles, one per line with bullets.",
    ),
    Variable(path="vehicles[0].year", label="First vehicle year", group="Vehicles", sample=2020),
    Variable(path="vehicles[0].make", label="First vehicle make", group="Vehicles", sample="Toyota"),
    Variable(path="vehicles[0].model", label="First vehicle model", group="Vehicles", sample="Camry"),
    Variable(path="vehicles[0].vin", label="First vehicle VIN", group="Vehicles", sample="1HG..."),
    *_expand("pricing", "Pricing", group="Pricing"),
    *_expand("carrier", "Carrier", group="Carrier"),
    *_expand("agent", "Agent", group="Sender", subgroup="Sales rep"),
    *_expand("org", "Org", group="Sender", subgroup="Company"),
    Variable(path="current_date", label="Today's date", group="Date & Time", sample="Apr 25, 2026", formatter="date_short"),
    Variable(path="current_year", label="Current year", group="Date & Time", sample=2026),
    Variable(path="tracking_link", label="Tracking link", group="Tracking", sample="https://app.thecargo.io/track/ORD-1234"),
)


# ── Helpers ──────────────────────────────────────────────────────────


def registry_tree() -> dict:
    """REGISTRY shaped for the UI: groups → subgroups → variables.

    The order of groups, subgroups, and items within each subgroup
    follows insertion order in :data:`REGISTRY` so authors control the
    picker layout by editing one file.
    """
    groups: dict[str, dict] = {}
    for v in REGISTRY:
        g = groups.setdefault(v.group, {"label": v.group, "subgroups": {}, "items": []})
        if v.subgroup:
            sg = g["subgroups"].setdefault(v.subgroup, {"label": v.subgroup, "items": []})
            sg["items"].append(_var_to_dict(v))
        else:
            g["items"].append(_var_to_dict(v))
    return {
        "version": VERSION,
        "groups": [
            {
                "label": g["label"],
                "items": g["items"],
                "subgroups": [
                    {"label": sg["label"], "items": sg["items"]}
                    for sg in g["subgroups"].values()
                ],
            }
            for g in groups.values()
        ],
        "schemas": {
            name: {
                "name": s.name,
                "label": s.label,
                "fields": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "sample": _coerce_json(f.sample),
                        "formatter": f.formatter,
                    }
                    for f in s.fields
                ],
            }
            for name, s in SCHEMAS.items()
        },
    }


def _var_to_dict(v: Variable) -> dict:
    """Serialize for the JSON registry payload.

    ``insert`` is intentionally left unset for plain scalar variables —
    the frontend computes the placeholder on the fly. Only true
    snippets (multi-token Liquid blocks the user shouldn't have to
    type by hand) ship a pre-baked ``insert`` string. Without this
    distinction the UI can't tell snippets from plain leaves and
    its "is this insertable?" check trips on every row.
    """
    out: dict = {
        "path": v.path,
        "label": v.label,
        "type": v.type.value,
        "object_schema": v.object_schema,
        "sample": _coerce_json(v.sample),
        "formatter": v.formatter,
        "description": v.description,
    }
    if v.insert:
        out["insert"] = v.insert
    return out


def _coerce_json(val: object | None) -> object | None:
    if val is None or isinstance(val, (str, int, float, bool, list, dict)):
        return val
    return str(val)


def sample_context() -> dict:
    """Best-effort sample context built from REGISTRY samples.

    Used by the editor's live preview when the user has no shipment
    selected, so the template still renders to something readable
    instead of empty placeholders.
    """
    ctx: dict = {}
    for v in REGISTRY:
        if v.type == VarType.ARRAY:
            ctx[v.path] = list(v.sample) if isinstance(v.sample, list) else []
            continue
        parts = v.path.split(".")
        cursor: dict = ctx
        for p in parts[:-1]:
            cursor = cursor.setdefault(p, {})
        if isinstance(cursor, dict):
            cursor[parts[-1]] = v.sample
    ctx.setdefault("vehicles", [
        {"year": 2020, "make": "Toyota", "model": "Camry", "vin": "1HG...", "color": "Blue", "is_inoperable": False},
        {"year": 2018, "make": "Honda", "model": "Civic", "vin": "2HG...", "color": "Red", "is_inoperable": False},
    ])
    ctx["_meta"] = {"locale": "en", "tz": "America/New_York", "currency": "USD"}
    return ctx


def suggest_correction(unknown_path: str, max_distance: int = 3) -> str | None:
    """Levenshtein-style suggestion for a typo'd variable path.

    Returns the closest known REGISTRY path within ``max_distance``
    edits, or ``None`` if nothing is reasonably close. Used by
    :func:`validate` to surface friendly "Did you mean…" hints.
    """
    best: tuple[int, str] | None = None
    candidates = [v.path for v in REGISTRY]
    for path in candidates:
        d = _levenshtein(unknown_path, path)
        if d <= max_distance and (best is None or d < best[0]):
            best = (d, path)
    return best[1] if best else None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
        prev = curr
    return prev[-1]


_ = field
