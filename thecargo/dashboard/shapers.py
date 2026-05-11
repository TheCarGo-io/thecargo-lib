"""
Pure shapers — turn raw service data into the response models the dashboard
frontend renders. Every function in here is deterministic and side-effect-free
so it can be reused from any service or unit-tested without IO.
"""

from __future__ import annotations

import calendar as _cal
import hashlib
import html
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from thecargo.dashboard.period import ResolvedPeriod
from thecargo.dashboard.schemas import (
    ActivityListItem,
    CalendarListItem,
    DashboardActivityResponse,
    DashboardCalendarResponse,
    DashboardChartAverage,
    DashboardChartFoot,
    DashboardChartHighLow,
    DashboardChartPoint,
    DashboardChartSeries,
    DashboardKpi,
    DashboardPerformanceResponse,
    DashboardPipelineResponse,
    DashboardQueueResponse,
    DashboardTargetsResponse,
    NeedsAttentionPanel,
    PipelineColumn,
    PipelineFootItem,
    QueueListItem,
    ReadyToShipPanel,
    TargetCard,
    WaitingOnCustomerPanel,
)

ORG_TZ = ZoneInfo("America/New_York")


def greeting_for(now: datetime) -> str:
    """Return 'Good morning' / 'Good afternoon' / 'Good evening' for a local datetime."""
    hour = now.hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _fmt_count(n: int) -> str:
    return f"{n:,}"


def _fmt_money(cents: int) -> str:
    dollars = (cents or 0) / 100.0
    if dollars >= 1_000_000:
        return f"${dollars / 1_000_000:.1f}M"
    if dollars >= 10_000:
        return f"${dollars / 1000:.1f}k".replace(".0k", "k")
    return f"${dollars:,.0f}"


def _safe_div(num: float, den: float) -> float | None:
    return num / den if den else None


def _delta_pct(now: float, prior: float) -> float | None:
    if not prior:
        return None
    return round((now - prior) / prior * 100.0, 1)


def _delta_pct_abs(now: float, prior: float) -> float | None:
    if prior is None:
        return None
    return round(now - prior, 1)


def _prior_label(period_key: str) -> str:
    return {
        "today": "Prior day",
        "7d": "Prior 7d",
        "30d": "Prior 30d",
        "mtd": "Prior month",
        "qtd": "Prior quarter",
        "custom": "Prior period",
    }.get(period_key, "Prior period")


def _fill_daily_gaps(
    rows_by_date: dict[date, dict[str, int]], from_date: date, to_date: date
) -> list[tuple[date, int, int]]:
    out: list[tuple[date, int, int]] = []
    cursor = from_date
    while cursor <= to_date:
        row = rows_by_date.get(cursor)
        out.append((cursor, (row or {}).get("charged_cents", 0), (row or {}).get("dispatched_revenue_cents", 0)))
        cursor += timedelta(days=1)
    return out


def _chart_label(d: date) -> str:
    return d.strftime("%b %-d")


def _date_long(d: date) -> str:
    return d.strftime("%b %-d, %a")


def _short_range_label(start: date, end: date) -> str:
    if start == end:
        return _chart_label(start)
    if start.month == end.month:
        return f"{_chart_label(start)}–{end.day}"
    return f"{_chart_label(start)}–{_chart_label(end)}"


def _build_chart(daily_rows: list[dict], window_from: date, window_to: date) -> DashboardChartSeries:
    by_date = {row["bucket_date"]: row for row in daily_rows}
    padded = _fill_daily_gaps(by_date, window_from, window_to)
    return DashboardChartSeries(
        labels=[_chart_label(d) for d, _, _ in padded],
        charged=[round(charged / 100.0, 2) for _, charged, _ in padded],
        dispatched=[round(disp / 100.0, 2) for _, _, disp in padded],
        title_meta=_short_range_label(window_from, window_to),
    )


def _build_foot(daily_rows: list[dict], window_from: date, window_to: date) -> DashboardChartFoot:
    by_date = {row["bucket_date"]: row for row in daily_rows}
    padded = _fill_daily_gaps(by_date, window_from, window_to)
    if not padded:
        zero = DashboardChartPoint(amount="$0", date="—")
        return DashboardChartFoot(
            highest=DashboardChartHighLow(charged=zero, dispatched=zero),
            lowest=DashboardChartHighLow(charged=zero, dispatched=zero),
            average=DashboardChartAverage(charged="$0", dispatched="$0"),
        )
    by_charged = sorted(padded, key=lambda r: r[1])
    by_dispatched = sorted(padded, key=lambda r: r[2])
    n = len(padded)
    avg_charged = sum(r[1] for r in padded) / n
    avg_disp = sum(r[2] for r in padded) / n
    return DashboardChartFoot(
        highest=DashboardChartHighLow(
            charged=DashboardChartPoint(amount=_fmt_money(by_charged[-1][1]), date=_date_long(by_charged[-1][0])),
            dispatched=DashboardChartPoint(
                amount=_fmt_money(by_dispatched[-1][2]), date=_date_long(by_dispatched[-1][0])
            ),
        ),
        lowest=DashboardChartHighLow(
            charged=DashboardChartPoint(amount=_fmt_money(by_charged[0][1]), date=_date_long(by_charged[0][0])),
            dispatched=DashboardChartPoint(
                amount=_fmt_money(by_dispatched[0][2]), date=_date_long(by_dispatched[0][0])
            ),
        ),
        average=DashboardChartAverage(charged=_fmt_money(int(avg_charged)), dispatched=_fmt_money(int(avg_disp))),
    )


def _build_kpis(current: dict, prior: dict, period_key: str) -> list[DashboardKpi]:
    prior_lbl = _prior_label(period_key)
    quotes_now = current["quotes"]
    quotes_prev = prior["quotes"]
    leads_now = current["leads"] or quotes_now
    quote_conv = _safe_div(quotes_now, leads_now)
    quoted_sub = f"{_fmt_count(quotes_now)} of {_fmt_count(leads_now)} leads  ·  {round((quote_conv or 0) * 100)}% con"
    dispatched_now_cents = current["dispatched_revenue_cents"]
    dispatched_prev_cents = prior["dispatched_revenue_cents"]
    dispatched_count = current["dispatched"]
    quote_to_dispatch = _safe_div(dispatched_count, quotes_now)
    dispatched_sub = (
        f"{_fmt_count(dispatched_count)} of {_fmt_count(quotes_now)} quotes  ·  "
        f"{round((quote_to_dispatch or 0) * 100)}% con"
    )
    orders_now = current["orders"] or 1
    dispatch_rate_now = dispatched_count / orders_now * 100.0 if orders_now else 0.0
    dispatch_rate_prev = prior["dispatched"] / (prior["orders"] or 1) * 100.0 if prior.get("orders") else 0.0
    rate_sub = f"{_fmt_count(dispatched_count)} of {_fmt_count(current['orders'])} orders"
    margin_cents_now = current["margin_cents"]
    margin_per_order_now = margin_cents_now / orders_now if orders_now else 0
    margin_cents_prev = prior["margin_cents"]
    margin_per_order_prev = margin_cents_prev / prior["orders"] if prior.get("orders") else 0
    revenue_now = current["dispatched_revenue_cents"] or 1
    margin_pct_now = margin_cents_now / revenue_now * 100.0 if revenue_now else 0
    margin_sub = f"{round(margin_pct_now)}% margin  ·  {_fmt_count(current['orders'])} orders"
    charged_now_cents = current["charged_cents"]
    collected_now_cents = current["collected_cents"]
    collected_prev_cents = prior["collected_cents"]
    pct_collected = collected_now_cents / charged_now_cents * 100.0 if charged_now_cents else 0
    due_cents = max(0, charged_now_cents - collected_now_cents)
    payments_sub = f"{round(pct_collected)}% of charged  ·  {_fmt_money(due_cents)} due"
    return [
        DashboardKpi(
            label="Quoted",
            value=_fmt_count(quotes_now),
            sub=quoted_sub,
            prior=f"{prior_lbl}: {_fmt_count(quotes_prev)}",
            delta=_delta_pct(quotes_now, quotes_prev),
        ),
        DashboardKpi(
            label="Dispatched",
            value=_fmt_money(dispatched_now_cents),
            sub=dispatched_sub,
            prior=f"{prior_lbl}: {_fmt_money(dispatched_prev_cents)}",
            delta=_delta_pct(dispatched_now_cents, dispatched_prev_cents),
        ),
        DashboardKpi(
            label="Dispatch rate",
            value=f"{round(dispatch_rate_now)}%",
            sub=rate_sub,
            prior=f"{prior_lbl}: {round(dispatch_rate_prev)}%",
            delta=_delta_pct_abs(dispatch_rate_now, dispatch_rate_prev),
        ),
        DashboardKpi(
            label="Avg margin / order",
            value=_fmt_money(int(margin_per_order_now)),
            sub=margin_sub,
            prior=f"{prior_lbl}: {_fmt_money(int(margin_per_order_prev))}",
            delta=_delta_pct(margin_per_order_now, margin_per_order_prev),
        ),
        DashboardKpi(
            label="Payments collected",
            value=_fmt_money(collected_now_cents),
            sub=payments_sub,
            prior=f"{prior_lbl}: {_fmt_money(collected_prev_cents)}",
            delta=_delta_pct(collected_now_cents, collected_prev_cents),
        ),
    ]


def shape_performance(
    raw: dict,
    *,
    user_full_name: str,
    resolved: ResolvedPeriod,
    scope_label: str,
) -> DashboardPerformanceResponse:
    """Build the Performance panel response.

    `raw` matches the structure returned by shipment's
    `POST /api/internal/analytics/aggregates`:
    `{"current": {...}, "prior": {...}, "daily": [{"bucket_date", "charged_cents", "dispatched_revenue_cents"}, ...]}`.
    """
    daily_rows = [
        {
            "bucket_date": date.fromisoformat(r["bucket_date"])
            if isinstance(r["bucket_date"], str)
            else r["bucket_date"],
            "charged_cents": r["charged_cents"],
            "dispatched_revenue_cents": r["dispatched_revenue_cents"],
        }
        for r in raw.get("daily", [])
    ]
    if scope_label == "team":
        user_name = f"{user_full_name}'s team"
    elif scope_label == "company":
        user_name = "Company"
    else:
        user_name = user_full_name
    return DashboardPerformanceResponse(
        user_name=user_name,
        period_label=resolved.label,
        kpis=_build_kpis(raw["current"], raw["prior"], resolved.period.value),
        chart=_build_chart(daily_rows, resolved.current.date_from, resolved.current.date_to),
        foot=_build_foot(daily_rows, resolved.current.date_from, resolved.current.date_to),
    )


def shape_pipeline(raw: dict, resolved: ResolvedPeriod) -> DashboardPipelineResponse:
    """Build the Pipeline panel response from the same aggregates payload as `shape_performance`."""
    cur = raw.get("current", {}) or {}
    prv = raw.get("prior", {}) or {}
    cols = [
        PipelineColumn(
            label="Leads", value=cur.get("leads", 0), delta=_delta_pct(cur.get("leads", 0), prv.get("leads", 0))
        ),
        PipelineColumn(
            label="Quotes", value=cur.get("quotes", 0), delta=_delta_pct(cur.get("quotes", 0), prv.get("quotes", 0))
        ),
        PipelineColumn(
            label="Orders", value=cur.get("orders", 0), delta=_delta_pct(cur.get("orders", 0), prv.get("orders", 0))
        ),
        PipelineColumn(
            label="Posted", value=cur.get("posted", 0), delta=_delta_pct(cur.get("posted", 0), prv.get("posted", 0))
        ),
        PipelineColumn(
            label="Dispatched",
            value=cur.get("dispatched", 0),
            delta=_delta_pct(cur.get("dispatched", 0), prv.get("dispatched", 0)),
        ),
        PipelineColumn(
            label="Delivered",
            value=cur.get("delivered", 0),
            delta=_delta_pct(cur.get("delivered", 0), prv.get("delivered", 0)),
        ),
    ]
    orders = cur.get("orders", 0)
    quotes = cur.get("quotes", 0)

    def _fmt_pct(num: int, den: int) -> str:
        return "0%" if not den else f"{round(num / den * 100)}%"

    def _fmt_days(seconds: int, dispatch_events: int) -> str:
        if not dispatch_events:
            return "—"
        return f"{seconds / dispatch_events / 86400:.1f} days"

    label_map = {
        "today": "today · vs yesterday",
        "7d": "this week · vs last week",
        "30d": "last 30 days · vs prior 30",
        "mtd": "month to date · vs last month",
        "qtd": "quarter to date · vs last quarter",
    }
    period_label = label_map.get(resolved.period.value, resolved.label + " · vs prior period")
    foot = [
        PipelineFootItem(label="Quote → Order", value=_fmt_pct(orders, quotes)),
        PipelineFootItem(
            label="Avg time to dispatch",
            value=_fmt_days(cur.get("avg_dispatch_seconds_sum", 0), cur.get("dispatch_event_count", 0)),
        ),
        PipelineFootItem(
            label="Avg margin",
            value=_fmt_money(int(cur.get("margin_cents", 0) / orders) if orders else 0),
        ),
    ]
    return DashboardPipelineResponse(period_label=period_label, cols=cols, foot=foot)


def _e(s: str | None) -> str:
    return html.escape(str(s)) if s else ""


def _relative_age(iso_or_dt: str | datetime | None) -> str:
    if iso_or_dt is None:
        return ""
    if isinstance(iso_or_dt, str):
        try:
            dt = datetime.fromisoformat(iso_or_dt.replace("Z", "+00:00"))
        except ValueError:
            return ""
    else:
        dt = iso_or_dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 60:
        return "now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


def _route_label(item: dict) -> str:
    parts: list[str] = []
    if item.get("origin_city"):
        parts.append(item["origin_city"])
    if item.get("destination_city"):
        parts.append(item["destination_city"])
    return " → ".join(_e(p) for p in parts)


def _stage_label(item: dict) -> str:
    stage = (item.get("stage") or "").title()
    code = item.get("code") or ""
    return f"{stage} <b>#{_e(code)}</b>"


def _needs_attention_left(item: dict) -> str:
    stage_label = _stage_label(item)
    status = (item.get("status") or "").replace("_", " ").lower()
    if item.get("reason"):
        reason = _e(item["reason"]).replace("_", " ")
        return f"{stage_label} · {reason}"
    return f"{stage_label} · {status}"


def _today_pill(estimated_pickup_at: str | None) -> str:
    if not estimated_pickup_at:
        return ""
    try:
        d = datetime.fromisoformat(estimated_pickup_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if d.date() == datetime.now(timezone.utc).date():
        return '<span class="dash-aq-pill">Today</span>'
    return _e(d.date().isoformat())


def shape_queue(raw: dict) -> DashboardQueueResponse:
    """Build the action-queue response from shipment's `/api/internal/dashboard/queue` payload."""
    na = raw.get("needs_attention", {}) or {}
    na_items = [
        QueueListItem(left=_needs_attention_left(it), right=_relative_age(it.get("updated_at")))
        for it in na.get("items", [])
    ]
    needs = NeedsAttentionPanel(
        count=na.get("count", 0),
        oldest=_relative_age(na.get("oldest_at")),
        items=na_items,
        more=max(0, na.get("count", 0) - len(na_items)),
    )
    rts = raw.get("ready_to_ship", {}) or {}
    rts_items = [
        QueueListItem(
            left=f"{_e(it.get('code', ''))} · {_route_label(it)}".strip(" ·"),
            right=_today_pill(it.get("estimated_pickup_at")),
        )
        for it in rts.get("items", [])
    ]
    ready = ReadyToShipPanel(
        count=rts.get("count", 0),
        posted=rts.get("posted", 0),
        not_posted=rts.get("not_posted", 0),
        items=rts_items,
        more=max(0, rts.get("count", 0) - len(rts_items)),
    )
    woc = raw.get("waiting_on_customer", {}) or {}
    woc_items = [
        QueueListItem(
            left=f"{_e(it.get('code', ''))} · {(it.get('status') or '').replace('_', ' ')}",
            right=_relative_age(it.get("updated_at")),
        )
        for it in woc.get("items", [])
    ]
    waiting = WaitingOnCustomerPanel(
        count=woc.get("count", 0),
        follow_up=woc.get("follow_up", 0),
        deposit_pending=woc.get("deposit_pending", 0),
        items=woc_items,
        more=max(0, woc.get("count", 0) - len(woc_items)),
    )
    return DashboardQueueResponse(needs_attention=needs, ready_to_ship=ready, waiting_on_customer=waiting)


_PILL_CLASS = {"pickup": "pickup", "delivery": "dropoff"}
_PILL_TEXT = {"pickup": "Pickup", "delivery": "Delivery"}


def _fmt_calendar_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.astimezone(ORG_TZ).strftime("%-I:%M %p")


def shape_calendar(raw: dict) -> DashboardCalendarResponse:
    """Build the calendar response from shipment's `/api/internal/dashboard/calendar` payload."""
    today_label = datetime.now(ORG_TZ).strftime("%b %-d")
    items: list[CalendarListItem] = []
    for it in raw.get("items", []):
        stop_type = it.get("stop_type") or "pickup"
        city = it.get("city")
        state = it.get("state")
        location = ", ".join(p for p in (city, state) if p)
        title_parts = [p for p in (it.get("vehicle_summary"), location) if p]
        text = " · ".join(title_parts) if title_parts else it.get("shipment_code", "")
        meta_parts = []
        if it.get("shipment_code"):
            meta_parts.append(f"Order #{it['shipment_code']}")
        if it.get("customer_name"):
            meta_parts.append(it["customer_name"])
        items.append(
            CalendarListItem(
                time=_fmt_calendar_time(it["scheduled_at"]) if it.get("scheduled_at") else "—",
                text=text,
                meta=" · ".join(meta_parts),
                tag=_PILL_TEXT.get(stop_type, stop_type.title()),
                cls=_PILL_CLASS.get(stop_type, stop_type),
            )
        )
    return DashboardCalendarResponse(date_label=today_label, items=items)


_ACTIVITY_PALETTE = [
    "#2fb344",
    "#214690",
    "#1c7ed6",
    "#ae3ec9",
    "#fab005",
    "#fd7e14",
    "#d63939",
    "#1f7a3a",
    "#5c7cfa",
    "#7048e8",
]
_ACTIVITY_VERB = {"create": "created", "update": "updated", "delete": "deleted"}


def _activity_color(actor_id: str | None, actor_email: str | None) -> str:
    seed = (actor_id or actor_email or "system").encode()
    h = int.from_bytes(hashlib.md5(seed).digest()[:4], "big")
    return _ACTIVITY_PALETTE[h % len(_ACTIVITY_PALETTE)]


def _activity_initials(email: str | None, actor_id: str | None) -> str:
    if email:
        local = email.split("@", 1)[0]
        parts = [p for p in local.replace(".", " ").replace("_", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        if parts:
            return parts[0][:2].upper()
    if actor_id:
        return actor_id[:2].upper()
    return "··"


def _activity_text(ev: dict) -> str:
    actor = html.escape(ev.get("actor_email") or "Someone")
    verb = _ACTIVITY_VERB.get(ev.get("action") or "", "modified")
    resource = (ev.get("resource") or "record").replace("_", " ")
    label = ev.get("resource_label") or ev.get("resource_id") or resource
    return f'<b>{actor}</b> {verb} <a href="#">{html.escape(str(label))}</a>'


def _activity_meta(ev: dict) -> str:
    service = ev.get("service") or ""
    changed = ev.get("changed_fields") or []
    if changed:
        return f"{service} · {', '.join(str(c) for c in changed[:3])}"
    return service


def shape_activity(raw: dict) -> DashboardActivityResponse:
    """Build the activity feed response from audit's list payload."""
    items_raw = raw.get("items", []) if isinstance(raw, dict) else []
    items: list[ActivityListItem] = []
    for ev in items_raw:
        items.append(
            ActivityListItem(
                actor=_activity_initials(ev.get("actor_email"), ev.get("actor_id")),
                color=_activity_color(ev.get("actor_id"), ev.get("actor_email")),
                text=_activity_text(ev),
                meta=_activity_meta(ev),
                time=_relative_age(ev.get("created_at", "")),
            )
        )
    return DashboardActivityResponse(date_label="last 24h", items=items)


_TARGET_METRIC_LABELS = {"charged": "Charged", "dispatched": "Dispatched"}


def _target_status(current_cents: int, target_cents: int, pace_expected_cents: float) -> tuple[str, str]:
    if not target_cents:
        return ("No target set", "ontrack")
    if pace_expected_cents <= 0:
        return ("On track", "ontrack")
    ratio = current_cents / pace_expected_cents
    if ratio >= 1.05:
        ahead_cents = int(current_cents - pace_expected_cents)
        return (f"Ahead by {_fmt_money(ahead_cents)}", "ahead")
    if ratio < 0.95:
        behind_cents = int(pace_expected_cents - current_cents)
        return (f"Behind by {_fmt_money(behind_cents)}", "behind")
    return ("On track", "ontrack")


def _target_pace(current_cents: int, target_cents: int, day_of_month: int, days_in_month: int) -> str:
    pct = round(current_cents / target_cents * 100) if target_cents else 0
    daily_needed = max(0, target_cents - current_cents) / max(1, days_in_month - day_of_month)
    if daily_needed > 0:
        return f"Pace {pct}% (day {day_of_month}/{days_in_month}) · {_fmt_money(int(daily_needed))}/day to catch up"
    return f"Pace {pct}% (day {day_of_month}/{days_in_month})"


def shape_targets(raw: dict, resolved: ResolvedPeriod, month_start: date, month_end: date) -> DashboardTargetsResponse:
    """Build the Targets panel from a payload of `{year, month, cards, daily}`.

    `cards` must already carry `metric`, `target_cents`, `current_cents` for each tile.
    The caller is responsible for joining year-targets (analytics) with actual cents
    (shipment aggregates) before invoking this shaper.
    """
    year = raw.get("year")
    month = raw.get("month")
    days_in_month = _cal.monthrange(year, month)[1] if year and month else 30
    day_of_month = month_end.day
    daily_rows = [
        {
            "bucket_date": date.fromisoformat(r["bucket_date"])
            if isinstance(r["bucket_date"], str)
            else r["bucket_date"],
            "charged_cents": r["charged_cents"],
            "dispatched_revenue_cents": r["dispatched_revenue_cents"],
        }
        for r in raw.get("daily", [])
    ]
    cards: list[TargetCard] = []
    for c in raw.get("cards", []):
        metric = c.get("metric") or ""
        target_cents = int(c.get("target_cents", 0) or 0)
        current_cents = int(c.get("current_cents", 0) or 0)
        pace_expected = day_of_month / max(1, days_in_month) * target_cents
        status_label, status_cls = _target_status(current_cents, target_cents, pace_expected)
        cards.append(
            TargetCard(
                metric=metric,
                label=_TARGET_METRIC_LABELS.get(metric, metric.title()),
                target=_fmt_money(target_cents),
                target_int=target_cents // 100,
                current=_fmt_money(current_cents),
                current_int=current_cents // 100,
                status=status_label,
                status_class=status_cls,
                pace=_target_pace(current_cents, target_cents, day_of_month, days_in_month),
                remaining=f"{max(0, days_in_month - day_of_month)} days remaining",
            )
        )
    chart = _build_chart(daily_rows, month_start, month_end)
    foot = _build_foot(daily_rows, month_start, month_end)
    month_name = month_start.strftime("%B")
    meta = f"{month_name} · day {day_of_month} of {days_in_month}"
    return DashboardTargetsResponse(meta=meta, cards=cards, chart=chart, foot=foot)
