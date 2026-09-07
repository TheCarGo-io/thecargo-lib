from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from thecargo.utils.timezone import (
    UTC,
    business_today,
    day_bounds_utc,
    end_of_day_utc,
    ensure_aware,
    expand_day_bound,
    range_bounds_utc,
    start_of_day_utc,
    to_utc,
    utc_now,
    validate_iana,
)

NY = "America/New_York"
TASHKENT = "Asia/Tashkent"


def test_utc_now_is_aware_utc():
    now = utc_now()
    assert now.tzinfo is UTC


def test_ensure_aware_stamps_naive_and_keeps_aware():
    naive = datetime(2026, 8, 5, 12, 0)
    assert ensure_aware(naive).tzinfo is UTC
    aware = datetime(2026, 8, 5, 12, 0, tzinfo=ZoneInfo(NY))
    assert ensure_aware(aware) is aware
    assert ensure_aware(None) is None


def test_to_utc_converts_and_assumes():
    aware = datetime(2026, 8, 5, 20, 0, tzinfo=ZoneInfo(NY))
    assert to_utc(aware) == datetime(2026, 8, 6, 0, 0, tzinfo=UTC)
    naive = datetime(2026, 8, 5, 20, 0)
    assert to_utc(naive, assume=ZoneInfo(NY)) == datetime(2026, 8, 6, 0, 0, tzinfo=UTC)
    assert to_utc(None) is None


def test_validate_iana_accepts_names_and_utc():
    assert validate_iana(NY) == NY
    assert validate_iana("UTC") == "UTC"


@pytest.mark.parametrize("bad", ["EST", "PST", "+05:00", "America/Nowhere", ""])
def test_validate_iana_rejects_non_iana(bad):
    with pytest.raises(ValueError):
        validate_iana(bad)


def test_day_bounds_are_half_open_local_midnights():
    start, end = day_bounds_utc(date(2026, 8, 5), NY)
    assert start == datetime(2026, 8, 5, 4, 0, tzinfo=UTC)
    assert end == datetime(2026, 8, 6, 4, 0, tzinfo=UTC)
    assert end == start_of_day_utc(date(2026, 8, 6), NY)


def test_day_bounds_across_dst_spring_forward():
    start, end = day_bounds_utc(date(2026, 3, 8), NY)
    assert end - start == timedelta(hours=23)


def test_day_bounds_differ_by_zone():
    ny_start = start_of_day_utc(date(2026, 8, 5), NY)
    tk_start = start_of_day_utc(date(2026, 8, 5), TASHKENT)
    assert ny_start - tk_start == timedelta(hours=9)


def test_end_of_day_never_uses_time_max():
    end = end_of_day_utc(date(2026, 8, 5), NY)
    assert end.astimezone(ZoneInfo(NY)).time() == time.min


def test_range_bounds_handles_open_ends():
    lower, upper = range_bounds_utc(date(2026, 8, 1), None, NY)
    assert lower == start_of_day_utc(date(2026, 8, 1), NY)
    assert upper is None
    lower, upper = range_bounds_utc(None, date(2026, 8, 5), NY)
    assert lower is None
    assert upper == end_of_day_utc(date(2026, 8, 5), NY)


def test_expand_day_bound_widens_dates():
    assert expand_day_bound(date(2026, 8, 5), upper=False, tz=NY) == start_of_day_utc(date(2026, 8, 5), NY)
    assert expand_day_bound(date(2026, 8, 5), upper=True, tz=NY) == end_of_day_utc(date(2026, 8, 5), NY)


def test_expand_day_bound_passes_aware_instants_through():
    instant = datetime(2026, 8, 5, 14, 30, tzinfo=timezone(timedelta(hours=-4)))
    assert expand_day_bound(instant, upper=True, tz=NY) is instant


def test_expand_day_bound_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        expand_day_bound(datetime(2026, 8, 5, 14, 30), upper=False, tz=NY)


def test_business_today_matches_zone_clock():
    assert business_today(NY) == datetime.now(ZoneInfo(NY)).date()


def test_latest_instant_is_one_microsecond_before_next_midnight():
    from datetime import timedelta

    from thecargo.utils.timezone import latest_instant_of_day

    day = date(2026, 8, 5)
    assert end_of_day_utc(day, NY) - latest_instant_of_day(day, NY) == timedelta(microseconds=1)
