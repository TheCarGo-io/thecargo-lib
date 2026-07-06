from __future__ import annotations

import phonenumbers
from phonenumbers import timezone as _pn_timezone

from thecargo.utils.phone import normalize_phone

__all__ = ["timezones_for_number"]


def timezones_for_number(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    normalized = normalize_phone(value) or value
    try:
        parsed = phonenumbers.parse(normalized, "US")
    except phonenumbers.NumberParseException:
        return ()
    zones = _pn_timezone.time_zones_for_number(parsed)
    return tuple(zones) if zones else ()
