from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from fastapi import HTTPException

ORG_TZ = ZoneInfo("America/New_York")


class Period(str, Enum):
    TODAY = "today"
    LAST_7D = "7d"
    LAST_30D = "30d"
    MTD = "mtd"
    QTD = "qtd"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class DateWindow:
    date_from: date
    date_to: date

    @property
    def span_days(self) -> int:
        return (self.date_to - self.date_from).days + 1


@dataclass(frozen=True, slots=True)
class ResolvedPeriod:
    period: Period
    current: DateWindow
    prior: DateWindow
    label: str


def _today_in_org_tz() -> date:
    return datetime.now(ORG_TZ).date()


def _format_label(period: Period, w: DateWindow) -> str:
    fmt_short = "%b %-d"
    same_month = w.date_from.month == w.date_to.month
    if w.date_from == w.date_to:
        date_part = w.date_from.strftime(fmt_short)
    elif same_month:
        date_part = f"{w.date_from.strftime(fmt_short)}–{w.date_to.day}"
    else:
        date_part = f"{w.date_from.strftime(fmt_short)}–{w.date_to.strftime(fmt_short)}"
    if period == Period.TODAY:
        return f"Today · {date_part}"
    if period == Period.LAST_7D:
        return f"Last 7 days · {date_part}"
    if period == Period.LAST_30D:
        return f"Last 30 days · {date_part}"
    if period == Period.MTD:
        return f"Month to date · {date_part}"
    if period == Period.QTD:
        return f"Quarter to date · {date_part}"
    return date_part


def _quarter_start(d: date) -> date:
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def resolve_period(period: Period, date_from: date | None = None, date_to: date | None = None) -> ResolvedPeriod:
    today = _today_in_org_tz()
    if period == Period.TODAY:
        current = DateWindow(today, today)
        prior = DateWindow(today - timedelta(days=1), today - timedelta(days=1))
    elif period == Period.LAST_7D:
        current = DateWindow(today - timedelta(days=6), today)
        prior = DateWindow(today - timedelta(days=13), today - timedelta(days=7))
    elif period == Period.LAST_30D:
        current = DateWindow(today - timedelta(days=29), today)
        prior = DateWindow(today - timedelta(days=59), today - timedelta(days=30))
    elif period == Period.MTD:
        start = date(today.year, today.month, 1)
        current = DateWindow(start, today)
        prev_month_end = start - timedelta(days=1)
        prev_month_start = date(prev_month_end.year, prev_month_end.month, 1)
        prior_end = min(
            date(prev_month_end.year, prev_month_end.month, today.day)
            if today.day <= prev_month_end.day
            else prev_month_end,
            prev_month_end,
        )
        prior = DateWindow(prev_month_start, prior_end)
    elif period == Period.QTD:
        start = _quarter_start(today)
        current = DateWindow(start, today)
        prev_q_end = start - timedelta(days=1)
        prev_q_start = _quarter_start(prev_q_end)
        prior = DateWindow(prev_q_start, min(prev_q_end, prev_q_start + (today - start)))
    else:
        if not date_from or not date_to:
            raise HTTPException(400, "period=custom requires date_from and date_to")
        if date_to < date_from:
            raise HTTPException(400, "date_to must be on or after date_from")
        if (date_to - date_from).days > 366:
            raise HTTPException(400, "Custom range cannot exceed 366 days")
        current = DateWindow(date_from, date_to)
        span = current.span_days
        prior = DateWindow(date_from - timedelta(days=span), date_from - timedelta(days=1))
    return ResolvedPeriod(period=period, current=current, prior=prior, label=_format_label(period, current))
