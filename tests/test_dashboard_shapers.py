"""Regression + unit tests for the dashboard shapers.

Locks in the two Decimal-→500 bugs found in the analytics migration (Postgres
``SUM(bigint)`` returns ``Decimal``; shapers used to do ``Decimal / float``),
plus the team leaderboard logic and scope/name handling.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from thecargo.dashboard import Period, resolve_period, shape_queue, shape_team
from thecargo.dashboard.shapers import _fill_daily_gaps, _fmt_money


def _wrap(users):
    return {"users": users}


def _agent(uid, *, orders, dispatched, rev, prior_rev, margin=0, collected=0, quotes=0):
    return {
        "user_id": uid,
        "current": {
            "orders": orders,
            "dispatched": dispatched,
            "dispatched_revenue_cents": rev,
            "margin_cents": margin,
            "collected_cents": collected,
            "quotes": quotes,
        },
        "prior": {"dispatched_revenue_cents": prior_rev},
    }


# ── Decimal regressions ──────────────────────────────────────────────


def test_fmt_money_handles_decimal_and_none():
    assert _fmt_money(Decimal("2880000")) == "$28.8k"
    assert _fmt_money(Decimal("500000")) == "$5,000"
    assert _fmt_money(0) == "$0"
    assert _fmt_money(None) == "$0"


def test_fill_daily_gaps_coerces_decimal_to_int():
    rows = {date(2025, 8, 1): {"charged_cents": Decimal("100"), "dispatched_revenue_cents": Decimal("50")}}
    out = _fill_daily_gaps(rows, date(2025, 8, 1), date(2025, 8, 2))
    assert out[0] == (date(2025, 8, 1), 100, 50)
    assert out[1] == (date(2025, 8, 2), 0, 0)  # gap filled
    for _, charged, disp in out:
        assert isinstance(charged, int) and isinstance(disp, int)


def test_shape_team_survives_decimal_metrics():
    # The exact failure mode that 500'd: every metric arrives as Decimal.
    resolved = resolve_period(Period.LAST_7D)
    users = [
        {
            "user_id": "u1",
            "current": {k: Decimal("5") for k in ("orders", "dispatched", "quotes")}
            | {k: Decimal("500000") for k in ("dispatched_revenue_cents", "margin_cents", "collected_cents")},
            "prior": {"dispatched_revenue_cents": Decimal("0")},
        }
    ]
    resp = shape_team(_wrap(users), resolved)  # must not raise
    assert resp.team[0].dispatched == "$5,000"
    assert resp.averages.dispatched_label == "$5,000"


# ── Leaderboard logic ────────────────────────────────────────────────


def test_leaderboard_top_improved_coaching():
    resolved = resolve_period(Period.LAST_7D)
    users = [
        _agent("top", orders=10, dispatched=6, rev=900000, prior_rev=600000),  # highest rev, +50%
        _agent("improved", orders=10, dispatched=3, rev=300000, prior_rev=50000),  # +500%
        _agent("coaching", orders=10, dispatched=3, rev=80000, prior_rev=400000),  # -80%
    ]
    resp = shape_team(_wrap(users), resolved)
    assert resp.team_size == 3
    assert [m.user_id for m in resp.team] == ["top", "improved", "coaching"]  # sorted by dispatched desc
    assert resp.leaderboard.top_performer.user_id == "top"
    assert resp.leaderboard.top_performer.delta is None
    assert resp.leaderboard.most_improved.user_id == "improved"
    assert resp.leaderboard.most_improved.delta == 500.0
    assert resp.leaderboard.most_improved.trend == "up"
    assert resp.leaderboard.needs_coaching.user_id == "coaching"
    assert resp.leaderboard.needs_coaching.delta == -80.0
    assert resp.leaderboard.needs_coaching.trend == "down"


def test_leaderboard_skips_zero_prior_for_delta():
    resolved = resolve_period(Period.LAST_7D)
    users = [_agent("only", orders=5, dispatched=5, rev=500000, prior_rev=0)]
    resp = shape_team(_wrap(users), resolved)
    assert resp.leaderboard.top_performer.user_id == "only"  # ranks on current rev
    assert resp.leaderboard.most_improved is None  # prior=0 → undefined %
    assert resp.leaderboard.needs_coaching is None


def test_team_avg_rate_ignores_orderless_agents():
    # An agent with 0 orders must not drag the team-average dispatch rate to 0.
    resolved = resolve_period(Period.LAST_7D)
    users = [
        _agent("a", orders=10, dispatched=8, rev=100, prior_rev=0),  # 80%
        _agent("b", orders=0, dispatched=0, rev=0, prior_rev=0),  # no orders → excluded from rate avg
    ]
    resp = shape_team(_wrap(users), resolved)
    assert resp.averages.dispatch_rate == 80.0  # not 40.0


# ── Scope / names ────────────────────────────────────────────────────


def test_empty_team():
    resolved = resolve_period(Period.LAST_7D)
    resp = shape_team(_wrap([]), resolved)
    assert resp.team_size == 0
    assert resp.team == []
    assert resp.leaderboard.top_performer is None
    assert resp.averages.dispatched_label == "$0"


def test_names_null_when_unresolved_and_populated_when_given():
    resolved = resolve_period(Period.LAST_7D)
    users = [_agent("u1", orders=1, dispatched=1, rev=100, prior_rev=0)]
    assert shape_team(_wrap(users), resolved).team[0].name is None
    named = shape_team(
        _wrap(users),
        resolved,
        {"u1": {"name": "Jack Collins", "first_name": "Jack", "initials": "JC", "color": "#214690"}},
    )
    assert named.team[0].name == "Jack Collins"
    assert named.team[0].initials == "JC"


def test_shape_queue_accepts_native_dates():
    # regression: analytics calls shape_queue in-process with native date/datetime,
    # not ISO strings — _today_pill used to do `str.replace` on a date and crash.
    raw = {
        "needs_attention": {
            "count": 1,
            "oldest_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "items": [
                {
                    "code": "A1",
                    "stage": "quote",
                    "status": "follow_up",
                    "reason": None,
                    "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                }
            ],
        },
        "ready_to_ship": {
            "count": 1,
            "posted": 0,
            "not_posted": 1,
            "items": [
                {
                    "code": "O1",
                    "estimated_pickup_at": date(2026, 1, 2),
                    "origin_city": None,
                    "origin_state": None,
                    "dest_city": None,
                    "dest_state": None,
                }
            ],
        },
        "waiting_on_customer": {"count": 0, "follow_up": 0, "deposit_pending": 0, "items": []},
    }
    resp = shape_queue(raw)  # must not raise on native date/datetime
    assert resp.needs_attention.count == 1
    assert len(resp.ready_to_ship.items) == 1
