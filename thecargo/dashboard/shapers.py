from __future__ import annotations

import calendar as _cal
import html
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from thecargo.dashboard.period import ResolvedPeriod
from thecargo.dashboard.schemas import (
    ActivityActor,
    ActivityChange,
    ActivityFeedResponse,
    ActivityItem,
    ActivityLifecycle,
    ActivityResource,
    CalendarItemKind,
    CalendarListItem,
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
    DashboardTeamResponse,
    NeedsAttentionPanel,
    PipelineColumn,
    PipelineFootItem,
    QueueListItem,
    ReadyToShipPanel,
    TargetCard,
    TeamAverages,
    TeamLeaderboard,
    TeamLeaderCard,
    TeamMember,
    WaitingOnCustomerPanel,
)

ORG_TZ = ZoneInfo("America/New_York")


def greeting_for(now: datetime) -> str:
    hour = now.hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _fmt_count(n: int) -> str:
    return f"{n:,}"


def _fmt_money(cents: int) -> str:
    # Postgres SUM(bigint) returns Decimal; coerce so Decimal/float never TypeErrors.
    dollars = int(cents or 0) / 100.0
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
        row = rows_by_date.get(cursor) or {}
        # int(): Postgres SUM(bigint) returns Decimal; the chart does Decimal/float later.
        out.append((cursor, int(row.get("charged_cents", 0) or 0), int(row.get("dispatched_revenue_cents", 0) or 0)))
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


# Analytics has no user roster, so names default to None and the client fills
# them in from the user_id. Callers that DO own a replica may pass real names.
_DEFAULT_NAME = {"name": None, "first_name": None, "initials": None, "color": None}

_METRIC_KEYS = (
    "leads",
    "quotes",
    "orders",
    "dispatched",
    "delivered",
    "charged_cents",
    "dispatched_revenue_cents",
    "collected_cents",
    "margin_cents",
)


def _norm_metrics(d: dict) -> dict:
    """Coerce a per-agent metric row to plain ints.

    Postgres ``SUM(bigint)`` comes back as ``Decimal``; downstream money/rate
    math and ``_fmt_money`` must never see a Decimal (Decimal / float raises).
    """
    return {k: int(d.get(k) or 0) for k in _METRIC_KEYS}


def _team_kpis(cur: dict) -> tuple[int, int, float, int, int]:
    """(quotes, dispatched_cents, dispatch_rate_pct, avg_margin_cents, collected_cents) for one agent."""
    quotes = cur.get("quotes", 0)
    orders = cur.get("orders", 0)
    dispatched_count = cur.get("dispatched", 0)
    dispatched_cents = cur.get("dispatched_revenue_cents", 0)
    margin_cents = cur.get("margin_cents", 0)
    collected_cents = cur.get("collected_cents", 0)
    dispatch_rate = (dispatched_count / orders * 100.0) if orders else 0.0
    avg_margin_cents = int(margin_cents / orders) if orders else 0
    return quotes, dispatched_cents, dispatch_rate, avg_margin_cents, collected_cents


def _team_leaderboard(users: list[dict], names: dict[str, dict], prior_lbl: str) -> TeamLeaderboard:
    top: tuple[int, str, float] | None = None  # (dispatched_cents, user_id, rate)
    best: tuple[float, str, int] | None = None  # (delta_pct, user_id, dispatched_cents)
    worst: tuple[float, str, int] | None = None

    for u in users:
        uid = str(u["user_id"])
        cur = u.get("current", {}) or {}
        prv = u.get("prior", {}) or {}
        d_now = cur.get("dispatched_revenue_cents", 0)
        orders = cur.get("orders", 0)
        rate = (cur.get("dispatched", 0) / orders * 100.0) if orders else 0.0
        if top is None or d_now > top[0]:
            top = (d_now, uid, rate)
        d_prev = prv.get("dispatched_revenue_cents", 0)
        if d_prev > 0:
            delta = (d_now - d_prev) / d_prev * 100.0
            if best is None or delta > best[0]:
                best = (delta, uid, d_now)
            if worst is None or delta < worst[0]:
                worst = (delta, uid, d_now)

    def _card(uid: str, dispatched_cents: int, detail: str, delta: float | None, trend: str) -> TeamLeaderCard:
        nm = names.get(uid) or _DEFAULT_NAME
        return TeamLeaderCard(
            user_id=uid,
            name=nm["name"],
            initials=nm["initials"],
            color=nm["color"],
            dispatched=_fmt_money(dispatched_cents),
            detail=detail,
            delta=delta,
            trend=trend,
        )

    top_card = _card(top[1], top[0], f"{round(top[2])}% rate", None, "") if top and top[0] > 0 else None
    improved = (
        _card(best[1], best[2], f"+{round(best[0])}% vs {prior_lbl}", round(best[0], 1), "up")
        if best and best[0] > 0
        else None
    )
    coaching = (
        _card(worst[1], worst[2], f"{round(worst[0])}% vs {prior_lbl}", round(worst[0], 1), "down")
        if worst and worst[0] < 0
        else None
    )
    return TeamLeaderboard(top_performer=top_card, most_improved=improved, needs_coaching=coaching)


def shape_team(raw: dict, resolved: ResolvedPeriod, names: dict[str, dict] | None = None) -> DashboardTeamResponse:
    """Build the manager view: per-agent strip + team averages + leaderboard.

    ``names`` optionally maps user_id → {name, first_name, initials, color}. When
    omitted (analytics has no user roster), name/avatar fields are left null and
    the client resolves them from the user_id. The shaper itself stays DB-free.
    """
    names = names or {}
    prior_lbl = _prior_label(resolved.period.value).lower()
    # Normalise every metric row to int up front (Postgres SUM → Decimal) so the
    # strip, averages, and leaderboard all do clean int/float math.
    norm_users = [
        {
            "user_id": str(u["user_id"]),
            "current": _norm_metrics(u.get("current") or {}),
            "prior": _norm_metrics(u.get("prior") or {}),
        }
        for u in (raw.get("users", []) or [])
    ]

    members: list[TeamMember] = []
    sums = {"quotes": 0, "dispatched_cents": 0, "rate": 0.0, "margin": 0, "collected": 0}
    rate_n = 0  # agents with orders>0 — averaging a 0% rate over order-less agents is misleading.
    for u in norm_users:
        uid = u["user_id"]
        quotes, dispatched_cents, rate, avg_margin_cents, collected_cents = _team_kpis(u["current"])
        nm = names.get(uid) or _DEFAULT_NAME
        members.append(
            TeamMember(
                user_id=uid,
                name=nm["name"],
                first_name=nm["first_name"],
                initials=nm["initials"],
                color=nm["color"],
                quotes=quotes,
                dispatch_rate=f"{round(rate)}%",
                dispatched=_fmt_money(dispatched_cents),
                dispatched_int=dispatched_cents,
            )
        )
        sums["quotes"] += quotes
        sums["dispatched_cents"] += dispatched_cents
        sums["margin"] += avg_margin_cents
        sums["collected"] += collected_cents
        if u["current"].get("orders"):
            sums["rate"] += rate
            rate_n += 1

    members.sort(key=lambda m: m.dispatched_int, reverse=True)

    n = len(members)
    if n:
        avg_quoted = round(sums["quotes"] / n)
        avg_dispatched = int(sums["dispatched_cents"] / n)
        avg_rate = sums["rate"] / rate_n if rate_n else 0.0
        avg_margin = int(sums["margin"] / n)
        avg_collected = int(sums["collected"] / n)
        averages = TeamAverages(
            quoted=avg_quoted,
            quoted_label=_fmt_count(avg_quoted),
            dispatched_cents=avg_dispatched,
            dispatched_label=_fmt_money(avg_dispatched),
            dispatch_rate=round(avg_rate, 1),
            dispatch_rate_label=f"{round(avg_rate)}%",
            avg_margin_cents=avg_margin,
            avg_margin_label=_fmt_money(avg_margin),
            collected_cents=avg_collected,
            collected_label=_fmt_money(avg_collected),
        )
    else:
        averages = TeamAverages()

    return DashboardTeamResponse(
        period_label=f"Team · {resolved.label}",
        team_size=n,
        team=members,
        averages=averages,
        leaderboard=_team_leaderboard(norm_users, names, prior_lbl),
    )


def shape_pipeline(raw: dict, resolved: ResolvedPeriod) -> DashboardPipelineResponse:
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


def _today_pill(estimated_pickup_at: str | date | datetime | None) -> str:
    if not estimated_pickup_at:
        return ""
    # Accept native date/datetime (analytics in-process) as well as ISO strings (JSON).
    if isinstance(estimated_pickup_at, datetime):
        d = estimated_pickup_at.date()
    elif isinstance(estimated_pickup_at, date):
        d = estimated_pickup_at
    else:
        try:
            d = datetime.fromisoformat(str(estimated_pickup_at).replace("Z", "+00:00")).date()
        except ValueError:
            return ""
    if d == datetime.now(timezone.utc).date():
        return '<span class="dash-aq-pill">Today</span>'
    return _e(d.isoformat())


def shape_queue(raw: dict) -> DashboardQueueResponse:
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


_STOP_PILL_TEXT = {"pickup": "Pickup", "delivery": "Drop-off"}
_STOP_PILL_CLASS = {"pickup": "pickup", "delivery": "dropoff"}
_TASK_PILL_TEXT = {"phone": "Call", "payment": "Deposit", "general": "Follow up"}
_TASK_PILL_CLASS = {"phone": "call", "payment": "deposit", "general": "followup"}


def _parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_iso_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_iso_time(value: str | None):
    if value is None:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text).time()
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%H:%M:%S").time()
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None


def _task_at(task: dict) -> datetime | None:
    d = _parse_iso_date(task.get("date"))
    if d is None:
        return None
    t = _parse_iso_time(task.get("start_time"))
    if t is None:
        return None
    local = datetime.combine(d, t).replace(tzinfo=ORG_TZ)
    return local.astimezone(timezone.utc)


def _stop_row(stop: dict) -> CalendarListItem:
    stop_type = (stop.get("stop_type") or "pickup").lower()
    city = stop.get("city")
    state = stop.get("state")
    location = ", ".join(p for p in (city, state) if p)
    code = stop.get("shipment_code") or ""
    vehicle = stop.get("vehicle_summary")
    tag = _STOP_PILL_TEXT.get(stop_type, stop_type.title())
    cls = _STOP_PILL_CLASS.get(stop_type, stop_type)
    text = f"{tag} · {vehicle}" if vehicle else (f"{tag} · #{code}" if code else tag)
    meta_parts: list[str] = []
    if code:
        meta_parts.append(f"Order #{code}")
    if stop_type == "pickup" and stop.get("customer_name"):
        meta_parts.append(stop["customer_name"])
    if location:
        meta_parts.append(location)
    return CalendarListItem(
        at=_parse_iso(stop.get("scheduled_at")),
        text=text,
        meta=" · ".join(meta_parts),
        tag=tag,
        cls=cls,
        kind=CalendarItemKind.STOP,
        shipment_id=stop.get("shipment_id"),
    )


def _task_row(task: dict) -> CalendarListItem:
    raw_type = (task.get("type") or "general").lower()
    task_type = raw_type if raw_type in _TASK_PILL_TEXT else "general"
    tag = _TASK_PILL_TEXT[task_type]
    cls = _TASK_PILL_CLASS[task_type]
    code = task.get("shipment_code") or ""
    if task_type == "phone":
        text = f"Follow up · {task.get('assignee_name') or 'Unassigned'}"
        meta_bits: list[str] = []
        if code:
            meta_bits.append(f"Quote #{code}")
        days = task.get("days_since_last_contact")
        if isinstance(days, int) and days >= 0:
            meta_bits.append(f"{days} days since last contact")
        meta = " · ".join(meta_bits)
    elif task_type == "payment":
        amount_cents = task.get("amount_cents") or 0
        text = f"Deposit due · {_fmt_money(int(amount_cents))}"
        meta_bits = []
        if code:
            meta_bits.append(f"Quote #{code}")
        if task.get("customer_name"):
            meta_bits.append(task["customer_name"])
        meta = " · ".join(meta_bits)
    else:
        title = task.get("title") or "Follow up"
        text = f"Follow up · {title}"
        meta_bits = []
        if code:
            meta_bits.append(f"#{code}")
        if task.get("customer_name"):
            meta_bits.append(task["customer_name"])
        meta = " · ".join(meta_bits)
    return CalendarListItem(
        at=_task_at(task),
        text=text,
        meta=meta,
        tag=tag,
        cls=cls,
        kind=CalendarItemKind.TASK,
        shipment_id=task.get("shipment_id"),
        task_id=task.get("task_id"),
    )


def _follow_up_summary_row(summary: dict) -> CalendarListItem:
    count = int(summary.get("count") or 0)
    codes = list(summary.get("codes") or [])[:3]
    shipment_ids = list(summary.get("shipment_ids") or [])[:3]
    text = f"{count} quotes need follow-up today"
    meta = ", ".join(f"Q-{c}" for c in codes)
    return CalendarListItem(
        at=None,
        text=text,
        meta=meta,
        tag="Follow up",
        cls="followup",
        kind=CalendarItemKind.FOLLOW_UP_SUMMARY,
        shipment_ids=shipment_ids or None,
    )


def shape_calendar(raw: dict) -> DashboardCalendarResponse:
    today_label = datetime.now(ORG_TZ).strftime("%b %-d")
    if raw.get("date_label"):
        today_label = str(raw["date_label"])
    timed_items: list[CalendarListItem] = []
    for stop in raw.get("stops") or []:
        timed_items.append(_stop_row(stop))
    for task in raw.get("tasks") or []:
        timed_items.append(_task_row(task))
    timed_items.sort(key=lambda i: i.at or datetime.max.replace(tzinfo=timezone.utc))
    items: list[CalendarListItem] = list(timed_items)
    summary = raw.get("follow_up_summary")
    if summary and int(summary.get("count") or 0) > 0:
        items.append(_follow_up_summary_row(summary))
    return DashboardCalendarResponse(date_label=today_label, items=items)


def _activity_changes(ev: dict) -> list[ActivityChange]:
    changed = ev.get("changed_fields") or []
    old_data = ev.get("old_data") or {}
    new_data = ev.get("new_data") or {}
    return [ActivityChange(field=f, old=old_data.get(f), new=new_data.get(f)) for f in changed]


def _activity_lifecycle(ev: dict) -> ActivityLifecycle | None:
    raw = ev.get("lifecycle_transition")
    if not isinstance(raw, dict) or not raw.get("field"):
        return None
    return ActivityLifecycle.model_validate({"field": raw["field"], "from": raw.get("from"), "to": raw.get("to")})


def _activity_item(ev: dict) -> ActivityItem:
    user = ev.get("user") or {}
    return ActivityItem(
        id=str(ev.get("audit_id") or ev.get("id") or ""),
        created_at=str(ev.get("created_at") or ""),
        service=ev.get("service") or "",
        action=ev.get("action") or "",
        actor=ActivityActor(
            id=user.get("id"),
            email=user.get("email"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            type=user.get("type"),
        ),
        resource=ActivityResource(
            type=ev.get("resource") or "",
            id=ev.get("resource_id"),
            label=ev.get("resource_label"),
        ),
        changes=_activity_changes(ev),
        significant_fields=ev.get("significant_fields") or [],
        lifecycle=_activity_lifecycle(ev),
    )


def shape_activity(raw: dict) -> ActivityFeedResponse:
    items_raw = raw.get("items", []) if isinstance(raw, dict) else []
    return ActivityFeedResponse(date_label="last 24h", items=[_activity_item(ev) for ev in items_raw])


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
