"""Timezone primitives for the UTC core.

The core stores and computes in UTC; a timezone is applied only at the
boundary, and always arrives as an argument resolved from the user or the
organization — no function here falls back to an environment default.
"""

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime | None, assume: tzinfo = UTC) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=assume)


def to_utc(value: datetime | None, assume: tzinfo = UTC) -> datetime | None:
    aware = ensure_aware(value, assume)
    return aware.astimezone(UTC) if aware is not None else None


def validate_iana(name: str) -> str:
    """Accept only IANA zone names — abbreviations and raw offsets are ambiguous."""
    if name != "UTC" and "/" not in name:
        raise ValueError(f"not an IANA timezone name: {name!r}")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA timezone: {name!r}") from exc
    return name


def _zone(tz: tzinfo | str) -> tzinfo:
    return ZoneInfo(validate_iana(tz)) if isinstance(tz, str) else tz


def business_today(tz: tzinfo | str) -> date:
    return datetime.now(_zone(tz)).date()


def start_of_day_utc(day: date, tz: tzinfo | str) -> datetime:
    return datetime.combine(day, time.min, tzinfo=_zone(tz)).astimezone(UTC)


def end_of_day_utc(day: date, tz: tzinfo | str) -> datetime:
    """Exclusive upper bound: the next local midnight, never ``time.max``."""
    return start_of_day_utc(day + timedelta(days=1), tz)


def latest_instant_of_day(day: date, tz: tzinfo | str) -> datetime:
    """Inclusive upper bound for operators fixed to ``<=``: one microsecond —
    exactly Postgres's timestamptz resolution — before the next local midnight."""
    return end_of_day_utc(day, tz) - timedelta(microseconds=1)


def day_bounds_utc(day: date, tz: tzinfo | str) -> tuple[datetime, datetime]:
    return start_of_day_utc(day, tz), end_of_day_utc(day, tz)


def range_bounds_utc(
    date_from: date | None,
    date_to: date | None,
    tz: tzinfo | str,
) -> tuple[datetime | None, datetime | None]:
    lower = start_of_day_utc(date_from, tz) if date_from is not None else None
    upper = end_of_day_utc(date_to, tz) if date_to is not None else None
    return lower, upper


def expand_day_bound(value: date | datetime, *, upper: bool, tz: tzinfo | str) -> datetime:
    """Widen a bare day to the instant it means in ``tz``; pass instants through.

    A naive datetime is rejected rather than guessed at — the caller named
    neither a day nor an instant.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime bound: send a calendar day or an offset-bearing instant")
        return value
    return end_of_day_utc(value, tz) if upper else start_of_day_utc(value, tz)
