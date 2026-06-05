from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

VERSION = 3


class VarType(str, Enum):
    SCALAR = "scalar"
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    sample: object | None = None
    formatter: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ObjectSchema:
    name: str
    label: str
    fields: tuple[FieldDef, ...]


@dataclass(frozen=True)
class Variable:
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
        FieldDef("estimated_pickup_at", "Est. pickup", "2026-04-26", formatter="date_short"),
        FieldDef("estimated_delivery_at", "Est. delivery", "2026-04-29", formatter="date_short"),
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

COMPANY_SCHEMA = ObjectSchema(
    name="Company",
    label="Sender (your company)",
    fields=(
        FieldDef("name", "Company name", "TheCargo Inc"),
        FieldDef("department", "Department", "Logistics"),
        FieldDef("email", "Company email", "support@thecargo.io"),
        FieldDef("support_email", "Support email", "support@thecargo.io"),
        FieldDef("accounting_email", "Accounting email", "billing@thecargo.io"),
        FieldDef("phone", "Company phone", "(800) 555-0199", formatter="phone"),
        FieldDef("mainline", "Mainline", "(800) 555-0199", formatter="phone"),
        FieldDef("fax", "Fax", "(800) 555-0188", formatter="phone"),
        FieldDef("address", "Office address", "1200 Main St, Houston, TX 77006"),
        FieldDef("website", "Website", "https://thecargo.io"),
        FieldDef("logo", "Logo URL", "https://cdn.thecargo.io/logos/acme.png"),
        FieldDef("slug", "Slug", "thecargo"),
        FieldDef("short_code", "Short code (initials)", "TC"),
        FieldDef("code_letter", "Code letter", "T"),
        FieldDef("mon_fri", "Hours Mon–Fri", "9:00 AM – 6:00 PM"),
        FieldDef("saturday", "Hours Sat", "10:00 AM – 2:00 PM"),
        FieldDef("sunday", "Hours Sun", "Closed"),
    ),
)

PAYMENT_SCHEMA = ObjectSchema(
    name="Payment",
    label="Payment",
    fields=(
        FieldDef("invoice_number", "Invoice #", "INV-A1B2C3D4"),
        FieldDef("receipt_id", "Receipt ID", "1000A1B2C3D4"),
        FieldDef("amount", "Amount (base)", "120.00", formatter="currency"),
        FieldDef("amount_charged", "Amount charged", "125.00", formatter="currency"),
        FieldDef("total", "Total (with surcharge/discount)", "125.00", formatter="currency"),
        FieldDef("surcharge", "Surcharge", "5.00", formatter="currency"),
        FieldDef("surcharge_fee_rate", "Surcharge rate (%)", 4),
        FieldDef("discount", "Discount", "0.00", formatter="currency"),
        FieldDef("method", "Method (raw)", "credit_card"),
        FieldDef("method_display", "Method (display)", "Credit Card"),
        FieldDef("name_display", "Charge type / method", "Reservation"),
        FieldDef("reference", "Reference / Stripe invoice id", "in_1QabcDEFghiJK"),
        FieldDef("card_last4", "Card last 4", "4242"),
        FieldDef("paid_date", "Paid date (ISO)", "2026-05-14", formatter="date_short"),
        FieldDef("due_date_display", "Due date (display)", "May 25, 2026"),
    ),
)


SCHEMAS: dict[str, ObjectSchema] = {
    s.name: s
    for s in (
        CUSTOMER_SCHEMA,
        AGENT_SCHEMA,
        ORG_SCHEMA,
        COMPANY_SCHEMA,
        CARRIER_SCHEMA,
        STOP_SCHEMA,
        VEHICLE_SCHEMA,
        SHIPMENT_SCHEMA,
        PRICING_SCHEMA,
        PAYMENT_SCHEMA,
    )
}


# ── Top-level variable registry ──────────────────────────────────────


def _expand(prefix: str, schema_name: str, group: str, subgroup: str | None = None) -> tuple[Variable, ...]:
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


def _expand_delivery_stop(group: str, subgroup: str | None) -> tuple[Variable, ...]:
    samples = {
        "type": "delivery",
        "city": "Dallas",
        "state": "TX",
        "zip": "75201",
        "address": "550 Elm St",
        "business_name": "Dallas Auto Yard",
        "contact_name": "Sara Lee",
        "contact_phone": "(214) 555-7788",
        "scheduled_at": "2026-04-29T14:00:00",
    }
    schema = SCHEMAS["Stop"]
    return tuple(
        Variable(
            path=f"delivery.{f.key}",
            label=f.label,
            group=group,
            subgroup=subgroup,
            sample=samples.get(f.key, f.sample),
            formatter=f.formatter,
            description=f.description,
        )
        for f in schema.fields
    )


REGISTRY: tuple[Variable, ...] = (
    *_expand("customer", "Customer", group="Customer information", subgroup="Customer info"),
    Variable(
        path="vehicles_inline",
        label="Vehicle list (inline)",
        group="Shipping details",
        subgroup="Vehicle details",
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
        group="Shipping details",
        subgroup="Vehicle details",
        type=VarType.SCALAR,
        sample="• 2020 Toyota Camry\n• 2018 Honda Civic",
        insert=(
            "{% for v in vehicles %}- {{ v.year }} {{ v.make }} {{ v.model }}"
            "{% if v.is_inoperable %} (INOP){% endif %}\n{% endfor %}"
        ),
        description="All vehicles, one per line with bullets.",
    ),
    Variable(
        path="vehicles[0].year",
        label="First vehicle year",
        group="Shipping details",
        subgroup="Vehicle details",
        sample=2020,
    ),
    Variable(
        path="vehicles[0].make",
        label="First vehicle make",
        group="Shipping details",
        subgroup="Vehicle details",
        sample="Toyota",
    ),
    Variable(
        path="vehicles[0].model",
        label="First vehicle model",
        group="Shipping details",
        subgroup="Vehicle details",
        sample="Camry",
    ),
    Variable(
        path="vehicles[0].vin",
        label="First vehicle VIN",
        group="Shipping details",
        subgroup="Vehicle details",
        sample="1HG...",
    ),
    *_expand("shipment", "Shipment", group="Shipping details", subgroup="Shipping info"),
    *_expand("pickup", "Stop", group="Shipping details", subgroup="Origin information"),
    *_expand_delivery_stop(group="Shipping details", subgroup="Destination information"),
    Variable(
        path="tracking_link",
        label="Tracking link",
        group="Shipping details",
        subgroup="Other information",
        sample="https://app.thecargo.io/track/ORD-1234",
    ),
    *_expand("pricing", "Pricing", group="Price info", subgroup="Price information"),
    *_expand("payment", "Payment", group="Price info", subgroup="Payment details"),
    Variable(
        path="payment_url",
        label="Pay Now link",
        group="Price info",
        subgroup="Pay links",
        sample="https://pay.thecargo.io/pay-to-orders/abc?slug=acme",
        description="Hosted pay page for the customer to settle this invoice.",
    ),
    Variable(
        path="card_url",
        label="Card auth link",
        group="Price info",
        subgroup="Pay links",
        sample="https://app.thecargo.io/contract/cc-auth/abc/def",
        description="Credit-card authorization form URL.",
    ),
    Variable(
        path="sign_url",
        label="Contract sign link",
        group="Price info",
        subgroup="Pay links",
        sample="https://app.thecargo.io/contract/abc",
        description="Contract e-signature page URL.",
    ),
    *_expand("carrier", "Carrier", group="Carrier", subgroup="Carrier info"),
    *_expand("company", "Company", group="Company / User information", subgroup="Company information"),
    *_expand("agent", "Agent", group="Company / User information", subgroup="User information"),
    *_expand("org", "Org", group="Company / User information", subgroup="Company (legacy)"),
    Variable(
        path="current_date",
        label="Today's date",
        group="Date & Time",
        sample="Apr 25, 2026",
        formatter="date_short",
    ),
    Variable(
        path="current_year",
        label="Current year",
        group="Date & Time",
        sample=2026,
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────


def registry_tree() -> dict:
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
                "subgroups": [{"label": sg["label"], "items": sg["items"]} for sg in g["subgroups"].values()],
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
    ctx.setdefault(
        "vehicles",
        [
            {
                "year": 2020,
                "make": "Toyota",
                "model": "Camry",
                "vin": "1HG...",
                "color": "Blue",
                "is_inoperable": False,
            },
            {"year": 2018, "make": "Honda", "model": "Civic", "vin": "2HG...", "color": "Red", "is_inoperable": False},
        ],
    )
    ctx["_meta"] = {"locale": "en", "tz": "America/New_York", "currency": "USD"}
    return ctx


def suggest_correction(unknown_path: str, max_distance: int = 3) -> str | None:
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
