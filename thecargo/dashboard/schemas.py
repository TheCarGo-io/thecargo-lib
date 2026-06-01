"""
Response models the dashboard frontend expects.

Header / todo are kept as two separate responses because they live in two
different services (auth owns user + team, shipment owns the action queue),
so the frontend issues two requests and merges them. Every other panel maps
1-to-1 to a single service endpoint.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DashboardHeaderResponse(BaseModel):
    """Top-of-dashboard chrome — owned by the auth service.

    The todo chip is filled by a separate request to the shipment service
    (`GET /api/v1/dashboard/todo`); frontend merges the two responses.
    """

    time_label: str = Field(..., description="Localised current time, e.g. '6:32 PM'", examples=["6:32 PM"])
    greeting: str = Field(..., description="Time-of-day greeting", examples=["Good evening"])
    user_first_name: str = Field(..., description="First name shown after the greeting", examples=["Sarah"])
    team_count: int = Field(..., description="Active team members the caller belongs to", examples=[6])
    active_org_name: str | None = Field(
        None,
        description="Display name of the caller's active organization",
        examples=["ACME Logistics"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "time_label": "6:32 PM",
                "greeting": "Good evening",
                "user_first_name": "Sarah",
                "team_count": 6,
                "active_org_name": "ACME Logistics",
            }
        }
    )


class DashboardTodoResponse(BaseModel):
    """The number rendered inside the todo chip — owned by the shipment service.

    Counts everything that would land in the action queue's three panels
    (needs attention + ready to ship + waiting on customer).
    """

    count: int = Field(..., description="Aggregate count for the action queue chip", examples=[17])

    model_config = ConfigDict(json_schema_extra={"example": {"count": 17}})


class QueueListItem(BaseModel):
    left: str = Field(..., description="HTML for the left column (already escaped where needed)")
    right: str = Field(..., description="HTML for the right column (relative time or pill)")


class NeedsAttentionPanel(BaseModel):
    count: int
    oldest: str = Field("", description="Age of the oldest item, '2d' / '5h'")
    items: list[QueueListItem]
    more: int = 0


class ReadyToShipPanel(BaseModel):
    count: int
    posted: int
    not_posted: int
    items: list[QueueListItem]
    more: int = 0


class WaitingOnCustomerPanel(BaseModel):
    count: int
    follow_up: int
    deposit_pending: int
    items: list[QueueListItem]
    more: int = 0


class DashboardQueueResponse(BaseModel):
    needs_attention: NeedsAttentionPanel
    ready_to_ship: ReadyToShipPanel
    waiting_on_customer: WaitingOnCustomerPanel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "needs_attention": {
                    "count": 4,
                    "oldest": "2d",
                    "items": [
                        {"left": "Quote <b>#Q-1024</b> · waiting on docs", "right": "2d"},
                        {"left": "Order <b>#O-2031</b> · carrier_no_show", "right": "1d"},
                    ],
                    "more": 2,
                },
                "ready_to_ship": {
                    "count": 3,
                    "posted": 2,
                    "not_posted": 1,
                    "items": [
                        {"left": "O-2050 · Dallas → Phoenix", "right": '<span class="dash-aq-pill">Today</span>'}
                    ],
                    "more": 2,
                },
                "waiting_on_customer": {
                    "count": 5,
                    "follow_up": 3,
                    "deposit_pending": 2,
                    "items": [{"left": "Q-1019 · deposit pending", "right": "5h"}],
                    "more": 4,
                },
            }
        }
    )


class CalendarItemKind(str, Enum):
    """Discriminator the frontend keys off to route a click on a calendar row.

    `stop` rows open the shipment detail view, `task` rows open the toolbar
    task, and `follow_up_summary` opens the quotes-needing-follow-up list.
    """

    STOP = "stop"
    TASK = "task"
    FOLLOW_UP_SUMMARY = "follow_up_summary"


class CalendarListItem(BaseModel):
    at: datetime | None = Field(
        None,
        description="Tz-aware ISO timestamp. `null` = EOD / anytime today (used by `follow_up_summary`).",
    )
    text: str = Field(..., description="Primary line (event title)")
    meta: str = Field("", description="Secondary line (order ref, customer, follow-up codes, ...)")
    tag: str = Field(..., description="Pill text", examples=["Pickup", "Call", "Deposit", "Drop-off", "Follow up"])
    cls: str = Field(
        ...,
        description="Pill style suffix",
        examples=["pickup", "call", "deposit", "dropoff", "followup"],
    )
    kind: CalendarItemKind = Field(..., description="Discriminator for frontend click routing")
    shipment_id: UUID | None = Field(None, description="Set when kind=stop or kind=task")
    task_id: UUID | None = Field(None, description="Set when kind=task")
    shipment_ids: list[UUID] | None = Field(
        None,
        description="Parallel to the codes in `meta` for kind=follow_up_summary; first 3 only.",
    )


class DashboardCalendarResponse(BaseModel):
    date_label: str = Field(..., description="Header, e.g. 'Apr 29' or 'Today'")
    items: list[CalendarListItem]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date_label": "Apr 29",
                "items": [
                    {
                        "at": "2025-04-29T13:00:00+00:00",
                        "text": "Pickup · 2022 Tesla Model Y",
                        "meta": "Order #O-2050 · ACME Logistics · Dallas, TX",
                        "tag": "Pickup",
                        "cls": "pickup",
                        "kind": "stop",
                        "shipment_id": "1a2b3c4d-0000-0000-0000-000000000001",
                        "task_id": None,
                        "shipment_ids": None,
                    }
                ],
            }
        }
    )


class PipelineColumn(BaseModel):
    label: str
    value: int
    delta: float | None = Field(None, description="Signed % change vs prior period; null when prior was zero")


class PipelineFootItem(BaseModel):
    label: str
    value: str


class DashboardPipelineResponse(BaseModel):
    period_label: str
    cols: list[PipelineColumn]
    foot: list[PipelineFootItem]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "period_label": "this week · vs last week",
                "cols": [
                    {"label": "Leads", "value": 142, "delta": 17.4},
                    {"label": "Quotes", "value": 121, "delta": 12.0},
                    {"label": "Orders", "value": 88, "delta": 9.0},
                    {"label": "Posted", "value": 30, "delta": -3.2},
                    {"label": "Dispatched", "value": 71, "delta": 14.5},
                    {"label": "Delivered", "value": 62, "delta": 11.2},
                ],
                "foot": [
                    {"label": "Quote → Order", "value": "73%"},
                    {"label": "Avg time to dispatch", "value": "1.4 days"},
                    {"label": "Avg margin", "value": "$314"},
                ],
            }
        }
    )


class TargetCard(BaseModel):
    metric: str = Field(..., description="`charged` or `dispatched`")
    label: str
    target: str = Field(..., description="Formatted target, e.g. '$80,000'")
    target_int: int = Field(..., description="Numeric target in dollars (for client-side math)")
    current: str = Field(..., description="Formatted MTD actual, e.g. '$52,450'")
    current_int: int = Field(..., description="Numeric MTD actual in dollars")
    status: str = Field(..., description="Human label: 'On track' / 'Behind by $X' / 'Ahead by $X'")
    status_class: str = Field(..., description="UI suffix: `ontrack` / `behind` / `ahead`")
    pace: str = Field(..., description="Pace line, e.g. 'Pace 73% (day 22/30) · $2,827/day to catch up'")
    remaining: str = Field(..., description="Days remaining label, e.g. '8 days remaining'")


class DashboardChartSeries(BaseModel):
    labels: list[str] = Field(default_factory=list, description="Short labels for each day, e.g. 'Apr 16'")
    charged: list[float] = Field(default_factory=list, description="Charged amount per day")
    dispatched: list[float] = Field(default_factory=list, description="Dispatched revenue per day")
    title_meta: str = Field("", description="Human-readable date range shown beside the chart title, e.g. 'Apr 16–22'")


class DashboardChartPoint(BaseModel):
    amount: str = Field(..., description="Formatted money/number, e.g. '$1,500'")
    date: str = Field(..., description="Human-readable date label, e.g. 'Apr 21, Mon'")


class DashboardChartHighLow(BaseModel):
    charged: DashboardChartPoint
    dispatched: DashboardChartPoint


class DashboardChartAverage(BaseModel):
    charged: str = Field(..., description="Average charged across the window, e.g. '$586'")
    dispatched: str = Field(..., description="Average dispatched across the window, e.g. '$314'")


class DashboardChartFoot(BaseModel):
    highest: DashboardChartHighLow
    lowest: DashboardChartHighLow
    average: DashboardChartAverage


class DashboardTargetsResponse(BaseModel):
    meta: str = Field(..., description="Header sub-text, e.g. 'April · day 22 of 30'")
    cards: list[TargetCard]
    chart: DashboardChartSeries
    foot: DashboardChartFoot

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "meta": "April · day 22 of 30",
                "cards": [
                    {
                        "metric": "charged",
                        "label": "Charged",
                        "target": "$80,000",
                        "target_int": 80000,
                        "current": "$52,450",
                        "current_int": 52450,
                        "status": "Behind by $6,217",
                        "status_class": "behind",
                        "pace": "Pace 66% (day 22/30) · $3,444/day to catch up",
                        "remaining": "8 days remaining",
                    }
                ],
                "chart": {
                    "labels": ["Apr 1", "Apr 2"],
                    "charged": [2100.0, 3050.0],
                    "dispatched": [1400.0, 1800.0],
                    "title_meta": "Apr 1–22",
                },
                "foot": {
                    "highest": {
                        "charged": {"amount": "$4,200", "date": "Apr 18, Fri"},
                        "dispatched": {"amount": "$2,950", "date": "Apr 18, Fri"},
                    },
                    "lowest": {
                        "charged": {"amount": "$0", "date": "Apr 6, Sun"},
                        "dispatched": {"amount": "$0", "date": "Apr 6, Sun"},
                    },
                    "average": {"charged": "$2,384", "dispatched": "$1,610"},
                },
            }
        }
    )


class ActivityListItem(BaseModel):
    actor: str = Field(..., description="Initials shown in the avatar", examples=["AM"])
    color: str = Field(..., description="Avatar background colour", examples=["#214690"])
    text: str = Field(..., description="HTML for the activity line")
    meta: str = Field("", description="Secondary meta line")
    time: str = Field(..., description="Relative timestamp, '12m' / '1h'")


class DashboardActivityResponse(BaseModel):
    date_label: str = Field("last 24h", description="Header sub-text")
    items: list[ActivityListItem]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date_label": "last 24h",
                "items": [
                    {
                        "actor": "JR",
                        "color": "#214690",
                        "text": '<b>Jessica Ramirez</b> updated <a href="#">Shipment HG10115</a>',
                        "meta": "shipment · Pickup date 2026-06-30 · Delivery date 2026-06-30 · Available from 2026-05-10 → 2026-05-11",
                        "time": "12m",
                    },
                    {
                        "actor": "AM",
                        "color": "#2fb344",
                        "text": '<b>Anna Morrison</b> moved <a href="#">Order #HG10118</a> to Dispatched',
                        "meta": "shipment · Carrier pay $1,100 → $1,250",
                        "time": "1h",
                    },
                ],
            }
        }
    )


class ActivityActor(BaseModel):
    """Who performed the action.

    Denormalised from the JWT at write time, so a later rename never
    rewrites history. ``type`` is ``user`` for an authenticated
    operator and ``system`` for background / service-to-service writes
    (where ``id``/``email`` may be null). The client derives avatar
    initials and colour from these fields itself.
    """

    id: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    type: str | None = Field(None, description="`user` | `system`")


class ActivityResource(BaseModel):
    """The audited entity the event is about."""

    type: str = Field(..., description="Resource kind, e.g. `shipment`, `payment`, `tag`")
    id: str | None = None
    label: str | None = Field(None, description="Human label captured at write time, e.g. `Shipment HG10115`")


class ActivityChange(BaseModel):
    """One field-level diff.

    ``old``/``new`` are the raw stored values — strings, numbers,
    booleans, ISO dates, or name lists (e.g. ``tags``). Foreign-key
    columns carry a UUID; the client decides how to label and format
    each field. ``null`` on either side means the field was unset.
    """

    field: str
    old: Any = None
    new: Any = None


class ActivityLifecycle(BaseModel):
    """Stage/status transition extracted from an update, when present."""

    model_config = ConfigDict(populate_by_name=True)

    field: str = Field(..., description="`stage` or `status`")
    from_: Any = Field(None, alias="from")
    to: Any = None


class ActivityItem(BaseModel):
    """One raw activity row — the client renders text, avatar, and relative time.

    Carries the structured audit record (actor, resource, field diffs,
    lifecycle move, timestamp) instead of a pre-formatted line, so the
    frontend owns all copy, localisation, money/date formatting, and
    field labelling.
    """

    id: str = Field(..., description="Stable audit event id")
    created_at: str = Field(..., description="ISO-8601 timestamp; the client renders relative time")
    service: str = Field(..., description="Emitting service, e.g. `shipment`, `billing`")
    action: str = Field(..., description="`create` | `update` | `delete`")
    actor: ActivityActor
    resource: ActivityResource
    changes: list[ActivityChange] = Field(
        default_factory=list, description="Field-level diffs; empty for create / delete rows"
    )
    significant_fields: list[str] = Field(
        default_factory=list, description="Subset of changed fields the model flags business-critical"
    )
    lifecycle: ActivityLifecycle | None = None


class ActivityFeedResponse(BaseModel):
    date_label: str = Field("last 24h", description="Header sub-text")
    items: list[ActivityItem]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date_label": "last 24h",
                "items": [
                    {
                        "id": "9f1c2e3a-0000-4000-8000-000000000001",
                        "created_at": "2026-06-01T17:18:00-04:00",
                        "service": "shipment",
                        "action": "update",
                        "actor": {
                            "id": "ecb1ca08-9e8f-4270-ae6b-0ae1786de390",
                            "email": "jessica@thecargo.io",
                            "first_name": "Jessica",
                            "last_name": "Ramirez",
                            "type": "user",
                        },
                        "resource": {
                            "type": "shipment",
                            "id": "b2eb79be-4312-46d2-9a4b-1d48eb2546c1",
                            "label": "Shipment HG10115",
                        },
                        "changes": [
                            {"field": "estimated_pickup_at", "old": None, "new": "2026-06-30T00:00:00"},
                            {"field": "estimated_delivery_at", "old": None, "new": "2026-06-30T00:00:00"},
                            {"field": "first_available_date", "old": "2026-05-10", "new": "2026-05-11"},
                        ],
                        "significant_fields": [],
                        "lifecycle": None,
                    },
                    {
                        "id": "9f1c2e3a-0000-4000-8000-000000000002",
                        "created_at": "2026-06-01T16:05:00-04:00",
                        "service": "shipment",
                        "action": "update",
                        "actor": {
                            "id": "a11b...",
                            "email": "anna@thecargo.io",
                            "first_name": "Anna",
                            "last_name": "Morrison",
                            "type": "user",
                        },
                        "resource": {"type": "shipment", "id": "c3d4...", "label": "Order #HG10118"},
                        "changes": [{"field": "carrier_pay", "old": "1100.00", "new": "1250.00"}],
                        "significant_fields": ["carrier_pay"],
                        "lifecycle": {"field": "status", "from": "not_signed", "to": "dispatched"},
                    },
                ],
            }
        }
    )


class DashboardKpi(BaseModel):
    label: str = Field(..., description="Display label shown above the value", examples=["Quoted"])
    value: str = Field(..., description="Formatted main value", examples=["142", "$19.4k", "38%"])
    sub: str = Field("", description="Secondary line — denominator or context")
    prior: str = Field("", description="Prior-period label, e.g. 'Prior 7d: 121'")
    delta: float | None = Field(
        None,
        description=(
            "Signed percentage change vs the prior window. Positive = improvement; for "
            "`Dispatch rate` and `Avg margin` higher is better, so the sign is preserved "
            "as-is. `null` when there is no comparable prior window."
        ),
    )


class DashboardPerformanceResponse(BaseModel):
    user_name: str = Field(..., description="Display name shown in the header (caller's first+last)")
    period_label: str = Field(..., description="Period descriptor for the panel header, e.g. 'Last 7 days · Apr 16–22'")
    kpis: list[DashboardKpi] = Field(
        ...,
        description=(
            "Five KPI tiles in render order: Quoted, Dispatched, Dispatch rate, Avg margin / order, Payments collected."
        ),
    )
    chart: DashboardChartSeries
    foot: DashboardChartFoot

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_name": "Sarah Chen",
                "period_label": "Last 7 days · Apr 16–22",
                "kpis": [
                    {
                        "label": "Quoted",
                        "value": "142",
                        "sub": "142 of 142 leads  ·  100% con",
                        "prior": "Prior 7d: 121",
                        "delta": 17.0,
                    }
                ],
                "chart": {
                    "labels": ["Apr 16", "Apr 17", "Apr 18", "Apr 19", "Apr 20", "Apr 21", "Apr 22"],
                    "charged": [620, 880, 410, 380, 470, 1500, 1980],
                    "dispatched": [380, 410, 280, 0, 380, 900, 560],
                    "title_meta": "Apr 16–22",
                },
                "foot": {
                    "highest": {
                        "charged": {"amount": "$1,500", "date": "Apr 21, Mon"},
                        "dispatched": {"amount": "$900", "date": "Apr 21, Mon"},
                    },
                    "lowest": {
                        "charged": {"amount": "$0", "date": "Apr 19, Sat"},
                        "dispatched": {"amount": "$0", "date": "Apr 19, Sat"},
                    },
                    "average": {"charged": "$586", "dispatched": "$314"},
                },
            }
        }
    )
