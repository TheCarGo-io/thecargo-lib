"""Liquid filter implementations shared by every renderer.

Filter outputs must match liquidjs's client-side formatters byte for
byte — admin previews would lie otherwise. The companion JS file is
``admin/app/admin/statics/js/template-filters.js``; whenever a filter
changes here, update it there too and add a snapshot test.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def currency(value: object, code: str = "USD") -> str:
    """Format a numeric value as currency.

    Locale is en-US for now (org-level setting is the only locale we
    support), so formatting is fixed to ``$1,234.56``-style. The code
    suffix is suppressed for USD; other codes get an ISO-suffixed
    output like ``$1,234.56 EUR`` so the recipient can disambiguate.
    """
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount).quantize(Decimal("0.01"))
    whole, _, frac = format(amount, "f").partition(".")
    grouped = "{:,}".format(int(whole))
    body = f"${grouped}.{frac or '00'}"
    return f"{sign}{body}" if (code or "USD").upper() == "USD" else f"{sign}{body} {code.upper()}"


def phone(value: object) -> str:
    """Best-effort US phone formatter: ``(NNN) NNN-NNNN`` or ``+1 …``.

    Non-US-looking inputs fall through unchanged so international
    numbers don't get mangled.
    """
    if value in (None, ""):
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return str(value)


def _to_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _to_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def date_short(value: object) -> str:
    """``Apr 25, 2026`` — locale-fixed, terse."""
    d = _to_date(value)
    return d.strftime("%b %d, %Y") if d else ""


def date_long(value: object) -> str:
    """``April 25, 2026`` — full month name."""
    d = _to_date(value)
    return d.strftime("%B %d, %Y") if d else ""


def datetime_short(value: object) -> str:
    """``Apr 25, 2026 8:00 AM``."""
    dt = _to_datetime(value)
    return dt.strftime("%b %d, %Y %-I:%M %p") if dt else ""


def days_until(value: object) -> str:
    """Difference in days between today and the given date.

    Useful for "Your shipment ships in 3 days" snippets.
    """
    d = _to_date(value)
    if not d:
        return ""
    delta = (d - date.today()).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    return f"in {delta} days" if delta > 0 else f"{-delta} days ago"


def upper_first(value: object) -> str:
    s = str(value or "")
    return s[:1].upper() + s[1:] if s else s


def status_label(value: object) -> str:
    """Convert an internal status slug to a human label.

    ``follow_up`` → ``Follow up``, ``not_now`` → ``Not now``. Useful
    for shipment.status placeholders so end users don't see DB slugs.
    """
    s = str(value or "").replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else s


def default(value: object, fallback: str = "") -> str:
    """Liquid ships ``default`` already, but ours coerces empty strings
    too — handy when DB columns hold ``""`` instead of ``NULL``.
    """
    if value in (None, ""):
        return fallback
    return str(value)


FILTERS: dict[str, object] = {
    "currency": currency,
    "phone": phone,
    "date_short": date_short,
    "date_long": date_long,
    "datetime_short": datetime_short,
    "days_until": days_until,
    "upper_first": upper_first,
    "status_label": status_label,
    "default_str": default,
}
