"""Canonical lead-parsing field catalog.

Single source of truth for the fields shown on the Lead Source review
screen (SHIPPER / LOCATION / VEHICLE / SHIPMENT). Both the communication
email parser (which grades each field against an inbound email) and the
shipment provider API (which renders a blank skeleton when a provider has
no parsed snapshot yet) build off this list, so the screen shows the same
rows in the same order everywhere.

``key`` is the stable UI identifier; ``item_name`` is the canonical key a
confirmed mapping is persisted under (a ``LeadParsingItem`` name), so the
catalog also defines how a reviewed field feeds the live parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

DATE_FORMATS = [
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%Y-%m-%d",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%m.%d.%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%m %d %Y",
    "%d %b %Y",
]


def parse_date(date_string: str | None) -> str | None:
    """Parse a human date in any supported format to ISO ``YYYY-MM-DD``."""
    if not date_string:
        return None
    date_string = date_string.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(date_string, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


_VALIDATORS = {
    "email": lambda v: "@" in v and "." in v.split("@")[-1],
    "phone": lambda v: len(_digits(v)) >= 7,
    "pickup_state": lambda v: bool(re.fullmatch(r"[A-Za-z]{2}", v.strip())),
    "delivery_state": lambda v: bool(re.fullmatch(r"[A-Za-z]{2}", v.strip())),
    "pickup_zip": lambda v: bool(re.fullmatch(r"\d{5}(?:-\d{4})?", v.strip())),
    "delivery_zip": lambda v: bool(re.fullmatch(r"\d{5}(?:-\d{4})?", v.strip())),
    "year": lambda v: len(_digits(v)) == 4 and 1900 <= int(_digits(v)) <= 2100,
    "ship_date": lambda v: parse_date(v) is not None,
}


def field_status(key: str, value: str | None) -> str:
    """Grade one field's value: ``matched`` / ``review`` / ``not_found``.

    Empty is ``not_found``; otherwise the per-field type check decides
    ``matched`` (valid) vs ``review`` (present but low-confidence, e.g. a
    ship date of "ASAP" or a non-numeric zip). Re-running this on an edited
    value is what flips a corrected field from ``review`` to ``matched``.
    """
    v = (value or "").strip()
    if not v:
        return "not_found"
    return "matched" if _VALIDATORS.get(key, lambda x: bool(x.strip()))(v) else "review"


LEAD_FIELD_CATALOG: list[dict] = [
    {
        "key": "full_name",
        "section": "SHIPPER",
        "label": "FULL NAME",
        "item_name": "customer_name",
        "labels": ["full name", "customer name", "shipper name", "contact name", "name"],
    },
    {
        "key": "phone",
        "section": "SHIPPER",
        "label": "PHONE",
        "item_name": "customer_phone",
        "labels": ["phone number", "telephone", "cell phone", "mobile", "phone", "tel", "cell"],
    },
    {
        "key": "email",
        "section": "SHIPPER",
        "label": "EMAIL",
        "item_name": "customer_email",
        "labels": ["email address", "e-mail", "email"],
    },
    {
        "key": "pickup_city",
        "section": "LOCATION",
        "label": "PICKUP CITY",
        "item_name": "origin_city",
        "labels": ["pickup city", "origin city", "from city", "pickup", "origin"],
    },
    {
        "key": "pickup_state",
        "section": "LOCATION",
        "label": "PICKUP STATE",
        "item_name": "origin_state",
        "labels": ["pickup state", "origin state"],
    },
    {
        "key": "pickup_zip",
        "section": "LOCATION",
        "label": "PICKUP ZIP",
        "item_name": "origin_zip",
        "labels": ["pickup zip code", "pickup zipcode", "pickup zip", "origin zip"],
    },
    {
        "key": "delivery_city",
        "section": "LOCATION",
        "label": "DELIVERY CITY",
        "item_name": "destination_city",
        "labels": ["delivery city", "destination city", "dropoff city", "to city", "delivery", "destination"],
    },
    {
        "key": "delivery_state",
        "section": "LOCATION",
        "label": "DELIVERY STATE",
        "item_name": "destination_state",
        "labels": ["delivery state", "destination state"],
    },
    {
        "key": "delivery_zip",
        "section": "LOCATION",
        "label": "DELIVERY ZIP",
        "item_name": "destination_zip",
        "labels": ["delivery zip code", "delivery zipcode", "delivery zip", "destination zip"],
    },
    {
        "key": "year",
        "section": "VEHICLE",
        "label": "YEAR",
        "item_name": "vehicle_year",
        "labels": ["vehicle year", "year"],
    },
    {
        "key": "make",
        "section": "VEHICLE",
        "label": "MAKE",
        "item_name": "vehicle_make",
        "labels": ["vehicle make", "make"],
    },
    {
        "key": "model",
        "section": "VEHICLE",
        "label": "MODEL",
        "item_name": "vehicle_model",
        "labels": ["vehicle model", "model"],
    },
    {
        "key": "condition",
        "section": "VEHICLE",
        "label": "CONDITION",
        "item_name": "condition",
        "labels": ["running condition", "condition", "operable", "runs"],
    },
    {
        "key": "trailer_type",
        "section": "VEHICLE",
        "label": "TRAILER TYPE",
        "item_name": "transport_type",
        "labels": ["trailer type", "transport type", "carrier type", "transport"],
    },
    {
        "key": "vehicle_type",
        "section": "VEHICLE",
        "label": "VEHICLE TYPE",
        "item_name": "vehicle_type",
        "labels": ["vehicle type", "body type", "type"],
    },
    {
        "key": "ship_date",
        "section": "SHIPMENT",
        "label": "SHIP DATE",
        "item_name": "first_available_date",
        "labels": ["first available date", "available date", "pickup date", "ready date", "ship date"],
    },
    {
        "key": "notes",
        "section": "SHIPMENT",
        "label": "NOTES",
        "item_name": "notes",
        "labels": ["additional info", "comments", "remarks", "comment", "notes", "note"],
    },
]


SECTION_ORDER: list[str] = ["SHIPPER", "LOCATION", "VEHICLE", "SHIPMENT"]

REQUIRED_LEAD_FIELD_KEYS: list[str] = [
    "full_name",
    "phone",
    "pickup_city",
    "delivery_city",
    "year",
    "make",
    "model",
]


def blank_lead_preview() -> dict:
    """Return an empty preview: every catalog field present but unfilled.

    Used as the skeleton when a provider has no parsed email snapshot, so
    the review screen always renders the full field list (matching how the
    role screen lists every resource even when none are assigned).
    """
    fields = [
        {
            "key": spec["key"],
            "section": spec["section"],
            "label": spec["label"],
            "item_name": spec["item_name"],
            "value": None,
            "source": None,
            "matched_label": None,
            "status": "not_found",
            "hint": "no match found in email",
        }
        for spec in LEAD_FIELD_CATALOG
    ]
    return {"fields": fields, "summary": {"matched": 0, "review": 0, "not_found": len(fields)}}


def extract_lines(text: str | None) -> list[str]:
    """Keep only ``key: value`` lines, normalized and stripped.

    The parser matches whole lines, so anything without a colon separator
    (greetings, signatures, blank lines) is dropped up front to cut false
    positives before matching.
    """
    text = (text or "").strip().replace("\r\n", "\n")
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line and re.match(r".+?:.+", line):
            lines.append(line)
    return lines


@dataclass(frozen=True)
class FieldSpec:
    """One catalog row in the compact shape the matcher iterates over."""

    key: str
    section: str
    label: str
    item_name: str


FIELD_CATALOG: list[FieldSpec] = [
    FieldSpec(spec["key"], spec["section"], spec["label"], spec["item_name"]) for spec in LEAD_FIELD_CATALOG
]

ITEM_TO_FIELD: dict[str, str] = {spec.item_name: spec.key for spec in FIELD_CATALOG}

DEFAULT_LABELS: dict[str, list[str]] = {spec["key"]: spec.get("labels", []) for spec in LEAD_FIELD_CATALOG}


def _custom_labels_by_field(parsing_values: list[dict]) -> dict[str, list[str]]:
    """Group a provider's confirmed keyword values by review-screen field.

    ``parsing_values`` is the ``[{value, item_name}]`` shape; only item names
    that map onto a catalog field are kept (multi-vehicle ``vehicle2_*`` etc.
    are irrelevant to the single-vehicle review grid).
    """
    grouped: dict[str, list[str]] = {}
    for pv in parsing_values:
        field_key = ITEM_TO_FIELD.get(pv.get("item_name", ""))
        if not field_key:
            continue
        value = (pv.get("value") or "").strip().lower()
        if value:
            grouped.setdefault(field_key, []).append(value)
    return grouped


def _find_value(
    lines: list[str], labels: list[str], used: set[int]
) -> tuple[str | None, str | None, str | None, int | None]:
    """Return the first unused line whose text starts with one of ``labels``.

    Labels are tried longest-first so a specific label (``vehicle type``)
    wins over a generic one (``type``) on the same line. Returns the
    extracted value, the source line, the label that matched (persisted as
    the parse key on activation), and the line index so the caller can mark
    it consumed and stop two fields claiming the same line.
    """
    ordered = sorted(labels, key=len, reverse=True)
    for idx, line in enumerate(lines):
        if idx in used:
            continue
        line_lower = line.lower()
        for label in ordered:
            if line_lower.startswith(label):
                value = line[len(label) :].lstrip(" :\t-").strip()
                if value:
                    return value, line, label, idx
    return None, None, None, None


def parse_email_fields(text: str | None, parsing_values: list[dict] | None = None) -> dict:
    """Grade a raw email body against every catalog field for the review screen.

    A provider's confirmed keyword values take precedence; where it has none
    the built-in :data:`LEAD_FIELD_CATALOG` ``labels`` bootstrap the first
    guess. Each field is graded via :func:`field_status`:

    * ``matched`` — a value was extracted and passed its type check
    * ``review`` — a value was extracted but failed validation (e.g. a ship
      date of "ASAP", a non-numeric zip) and needs a human glance
    * ``not_found`` — no line matched; the dispatcher adds it manually

    Returns ``{"fields": [...], "summary": {...}}`` ready to persist as a
    provider's ``intake_preview`` and render verbatim. This is the single
    source of truth shared by the communication email pipeline, the shipment
    ``/api/v1/providers/parse-preview`` endpoint and the admin provider
    editor, so all three grade an identical email identically.
    """
    lines = extract_lines(text or "")
    custom = _custom_labels_by_field(parsing_values or [])
    used: set[int] = set()

    fields: list[dict] = []
    counts = {"matched": 0, "review": 0, "not_found": 0}

    for spec in FIELD_CATALOG:
        labels = custom.get(spec.key) or DEFAULT_LABELS.get(spec.key, [])
        value, source, matched_label, idx = _find_value(lines, labels, used)

        if value is None:
            status, hint = "not_found", "no match found in email"
        else:
            used.add(idx)
            status = field_status(spec.key, value)
            if status == "matched":
                hint = f'matched from "{source}"'
            else:
                hint = f'low confidence — matched "{value}"'

        counts[status] += 1
        fields.append(
            {
                "key": spec.key,
                "section": spec.section,
                "label": spec.label,
                "item_name": spec.item_name,
                "value": value,
                "source": source,
                "matched_label": matched_label,
                "status": status,
                "hint": hint,
            }
        )

    return {"fields": fields, "summary": counts}
