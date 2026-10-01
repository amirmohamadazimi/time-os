import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Meta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["observed"] = "observed"
    date_from: date | None = Field(None, alias="from")
    date_to: date | None = Field(None, alias="to")
    type: str | None = None
    session_count: int
    excluded_count: int


class PlannedVsActual(BaseModel):
    tasks: int
    estimated_minutes: float
    actual_minutes: float


class Summary(BaseModel):
    meta: Meta
    total_focus_minutes: float
    total_rest_minutes: float
    session_count: int
    rest_session_count: int
    active_days: int
    avg_daily_focus_minutes: float | None
    avg_session_minutes: float | None
    median_session_minutes: float | None
    longest_session_minutes: float | None
    total_paused_minutes: float
    completed_sessions: int
    stopped_sessions: int
    skipped_sessions: int
    switched_sessions: int
    unknown_end_sessions: int
    interrupted_sessions: int
    completion_rate: float | None
    interruption_rate: float | None
    tasks_considered: int
    tasks_completed: int
    task_completion_rate: float | None
    planned_vs_actual: PlannedVsActual


class PeriodPoint(BaseModel):
    period: date
    focus_minutes: float
    sessions: int


class Timeseries(BaseModel):
    meta: Meta
    granularity: Literal["day", "week", "month"]
    items: list[PeriodPoint]


class HourRow(BaseModel):
    hour: int
    focus_minutes: float
    sessions_started: int
    avg_session_minutes: float | None
    completion_rate: float | None


class ByHour(BaseModel):
    meta: Meta
    items: list[HourRow]


class WeekdayRow(BaseModel):
    weekday: int
    name: str
    focus_minutes: float
    days_in_range: int
    avg_daily_focus_minutes: float | None
    sessions: int
    avg_session_minutes: float | None
    completion_rate: float | None


class ByWeekday(BaseModel):
    meta: Meta
    items: list[WeekdayRow]


class ProjectRow(BaseModel):
    project_id: uuid.UUID | None
    project_name: str
    focus_minutes: float
    share: float
    sessions: int


class ByProject(BaseModel):
    meta: Meta
    items: list[ProjectRow]


class TagRow(BaseModel):
    tag: str
    focus_minutes: float
    share: float
    sessions: int


class ByTag(BaseModel):
    meta: Meta
    items: list[TagRow]


class Gaps(BaseModel):
    meta: Meta
    avg_gap_minutes: float | None
    median_gap_minutes: float | None
    samples: int


class EstimationRow(BaseModel):
    group: str
    group_id: uuid.UUID | None
    samples: int
    avg_estimate_minutes: float
    avg_actual_minutes: float
    ratio: float
    median_ratio: float
    multiplier: float
    weight: float
    confidence: Literal["insufficient", "moderate", "strong"]
    tendency: Literal["underestimate", "overestimate", "accurate"]


class EstimationMeta(BaseModel):
    kind: Literal["observed"] = "observed"
    tasks: int
    min_samples: int
    strong_samples: int


class Estimation(BaseModel):
    meta: EstimationMeta
    items: list[EstimationRow]


class Pattern(BaseModel):
    id: str
    kind: Literal["observed"]
    statement: str
    values: dict[str, Any]
    sample_size: int


class Patterns(BaseModel):
    meta: Meta
    items: list[Pattern]
