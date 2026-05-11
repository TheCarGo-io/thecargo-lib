"""
Shared dashboard primitives.

Each service exposes its own `/api/v1/dashboard/*` endpoints (frontend calls them
individually and composes the page). The shapers in this package are pure
functions that turn raw service data into the response models the frontend
expects, so every service emits the same shape without duplicating code.
"""

from thecargo.dashboard.period import DateWindow, Period, ResolvedPeriod, resolve_period
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
    DashboardHeaderResponse,
    DashboardKpi,
    DashboardPerformanceResponse,
    DashboardPipelineResponse,
    DashboardQueueResponse,
    DashboardTargetsResponse,
    DashboardTodoResponse,
    NeedsAttentionPanel,
    PipelineColumn,
    PipelineFootItem,
    QueueListItem,
    ReadyToShipPanel,
    TargetCard,
    WaitingOnCustomerPanel,
)
from thecargo.dashboard.shapers import (
    greeting_for,
    shape_activity,
    shape_calendar,
    shape_performance,
    shape_pipeline,
    shape_queue,
    shape_targets,
)

__all__ = [
    "ActivityListItem",
    "CalendarListItem",
    "DashboardActivityResponse",
    "DashboardCalendarResponse",
    "DashboardChartAverage",
    "DashboardChartFoot",
    "DashboardChartHighLow",
    "DashboardChartPoint",
    "DashboardChartSeries",
    "DashboardHeaderResponse",
    "DashboardKpi",
    "DashboardPerformanceResponse",
    "DashboardPipelineResponse",
    "DashboardQueueResponse",
    "DashboardTargetsResponse",
    "DashboardTodoResponse",
    "DateWindow",
    "NeedsAttentionPanel",
    "Period",
    "PipelineColumn",
    "PipelineFootItem",
    "QueueListItem",
    "ReadyToShipPanel",
    "ResolvedPeriod",
    "TargetCard",
    "WaitingOnCustomerPanel",
    "greeting_for",
    "resolve_period",
    "shape_activity",
    "shape_calendar",
    "shape_performance",
    "shape_pipeline",
    "shape_queue",
    "shape_targets",
]
