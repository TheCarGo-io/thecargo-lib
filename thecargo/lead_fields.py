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
    v = (value or "").strip()
    if not v:
        return "not_found"
    return "matched" if _VALIDATORS.get(key, lambda x: bool(x.strip()))(v) else "review"


LEAD_FIELD_CATALOG: list[dict] = [
    {
        "key": "first_name",
        "section": "SHIPPER",
        "label": "FIRST NAME",
        "item_name": "customer_first_name",
        "labels": [
            "first name",
            "fname",
            "given name",
            "full name",
            "customer name",
            "shipper name",
            "contact name",
            "name",
        ],
    },
    {
        "key": "last_name",
        "section": "SHIPPER",
        "label": "LAST NAME",
        "item_name": "customer_last_name",
        "labels": ["last name", "lname", "surname", "family name"],
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
        "labels": [
            "pickup zip code",
            "pickup zipcode",
            "pickup zip",
            "origin zip code",
            "origin zipcode",
            "origin zip",
        ],
    },
    {
        "key": "delivery_city",
        "section": "LOCATION",
        "label": "DELIVERY CITY",
        "item_name": "destination_city",
        "labels": [
            "delivery city",
            "destination city",
            "dropoff city",
            "drop off city",
            "to city",
            "dest city",
            "moving city",
            "delivery",
            "destination",
        ],
    },
    {
        "key": "delivery_state",
        "section": "LOCATION",
        "label": "DELIVERY STATE",
        "item_name": "destination_state",
        "labels": ["delivery state", "destination state", "dest state", "moving state"],
    },
    {
        "key": "delivery_zip",
        "section": "LOCATION",
        "label": "DELIVERY ZIP",
        "item_name": "destination_zip",
        "labels": [
            "delivery zip code",
            "delivery zipcode",
            "delivery zip",
            "destination zip code",
            "destination zipcode",
            "destination zip",
            "dest zip",
            "moving zip",
        ],
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
        "labels": [
            "first available date",
            "available date",
            "available_date",
            "move date",
            "moving date",
            "pickup date",
            "ready date",
            "ship date",
        ],
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
    "first_name",
    "phone",
    "pickup_city",
    "delivery_city",
    "year",
    "make",
    "model",
]


def blank_lead_preview() -> dict:
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
    return {
        "fields": fields,
        "vehicles": [],
        "summary": {"matched": 0, "review": 0, "not_found": len(fields), "vehicles_detected": 0},
    }


def extract_lines(text: str | None) -> list[str]:
    text = (text or "").strip().replace("\r\n", "\n")
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line and re.match(r".+?:.+", line):
            lines.append(line)
    return lines


@dataclass(frozen=True)
class FieldSpec:
    key: str
    section: str
    label: str
    item_name: str


FIELD_CATALOG: list[FieldSpec] = [
    FieldSpec(spec["key"], spec["section"], spec["label"], spec["item_name"]) for spec in LEAD_FIELD_CATALOG
]

ITEM_TO_FIELD: dict[str, str] = {spec.item_name: spec.key for spec in FIELD_CATALOG}

_LEGACY_ITEM_ALIASES: dict[str, str] = {"customer_name": "first_name"}

DEFAULT_LABELS: dict[str, list[str]] = {spec["key"]: spec.get("labels", []) for spec in LEAD_FIELD_CATALOG}


def _custom_labels_by_field(parsing_values: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for pv in parsing_values:
        item_name = pv.get("item_name", "")
        field_key = ITEM_TO_FIELD.get(item_name) or _LEGACY_ITEM_ALIASES.get(item_name)
        if not field_key:
            continue
        value = (pv.get("value") or "").strip().lower()
        if value:
            grouped.setdefault(field_key, []).append(value)
    return grouped


_LABEL_TAIL = r"\s*(\d*)\s*:"


def _scan_labels(text: str, labels_by_key: dict[str, list[str]]) -> list[tuple[int, int, str, int, str]]:
    lowered = text.lower()
    hits: list[tuple[int, int, str, int, int, str]] = []
    for key, labels in labels_by_key.items():
        for label in labels:
            norm = label.strip().rstrip(":").strip().lower()
            if not norm:
                continue
            for match in re.finditer(re.escape(norm) + _LABEL_TAIL, lowered):
                number = match.group(1)
                index = int(number) - 1 if number else 0
                hits.append((match.start(), match.end(), key, index, len(norm), norm))

    hits.sort(key=lambda hit: (hit[0], -hit[4]))
    kept: list[tuple[int, int, str, int, str]] = []
    last_end = -1
    for start, end, key, index, _, label in hits:
        if start >= last_end:
            kept.append((start, end, key, index, label))
            last_end = end
    return kept


def parse_email_fields(text: str | None, parsing_values: list[dict] | None = None) -> dict:
    text = text or ""
    custom = _custom_labels_by_field(parsing_values or [])
    labels_by_key = {spec.key: (custom.get(spec.key) or DEFAULT_LABELS.get(spec.key, [])) for spec in FIELD_CATALOG}

    kept = _scan_labels(text, labels_by_key)

    vehicle_keys = {spec.key for spec in FIELD_CATALOG if spec.section == "VEHICLE"}

    found: dict[str, dict[int, tuple[str, str, str]]] = {}
    vehicle_slots: set[int] = set()
    for position, (start, value_start, key, index, label) in enumerate(kept):
        if key in vehicle_keys:
            vehicle_slots.add(index)
        next_label = kept[position + 1][0] if position + 1 < len(kept) else len(text)
        line_end = text.find("\n", value_start)
        value_end = next_label if line_end == -1 else min(next_label, line_end)
        value = text[value_start:value_end].strip().strip(",;").strip()
        if not value:
            continue
        found.setdefault(key, {}).setdefault(index, (value, text[start:value_end].strip(), label))

    counts = {"matched": 0, "review": 0, "not_found": 0}

    def _emit(spec: FieldSpec, index: int, *, count: bool) -> dict:
        per_index = found.get(spec.key, {})
        if index in per_index:
            value, source, matched_label = per_index[index]
            status = field_status(spec.key, value)
            hint = f'matched from "{source}"' if status == "matched" else f'low confidence — matched "{value}"'
        else:
            value = source = matched_label = None
            status, hint = "not_found", "no match found in email"
        if count:
            counts[status] += 1
        return {
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

    fields = [_emit(spec, min(found[spec.key]) if found.get(spec.key) else 0, count=True) for spec in FIELD_CATALOG]

    vehicle_specs = [spec for spec in FIELD_CATALOG if spec.section == "VEHICLE"]
    vehicles = [[_emit(spec, idx, count=False) for spec in vehicle_specs] for idx in sorted(vehicle_slots)]

    return {
        "fields": fields,
        "vehicles": vehicles,
        "summary": {**counts, "vehicles_detected": len(vehicles)},
    }
