from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def currency(value: object, code: str = "USD") -> str:
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
    d = _to_date(value)
    return d.strftime("%b %d, %Y") if d else ""


def date_long(value: object) -> str:
    d = _to_date(value)
    return d.strftime("%B %d, %Y") if d else ""


def datetime_short(value: object) -> str:
    dt = _to_datetime(value)
    return dt.strftime("%b %d, %Y %-I:%M %p") if dt else ""


def days_until(value: object) -> str:
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
    s = str(value or "").replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else s


def default(value: object, fallback: str = "") -> str:
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
