"""Scheduler interface (contract for the Phase 4 engine). See docs/scheduler.md.

The engine exposes three pure functions over these types::

    generate_schedule(request: ScheduleRequest) -> ScheduleResult
    validate_blocks(request: ScheduleRequest, blocks: Sequence[ProposedBlock]) -> list[Violation]
    reschedule(request: ScheduleRequest, current: Sequence[ScheduledBlock],
               event: RescheduleEvent) -> RescheduleResult

Same input, same output: no database, clock or network access inside the engine.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Literal

BlockKind = Literal["task", "break", "buffer", "meal", "review", "calendar"]
UnscheduledReason = Literal[
    "no_capacity", "deadline_unreachable", "blocked_by_dependency", "not_yet_startable", "below_min_block"
]


@dataclass(frozen=True)
class Interval:
    start: datetime  # aware, UTC
    end: datetime

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass(frozen=True)
class BusyInterval(Interval):
    source: Literal["calendar", "meal", "personal", "fixed_block"] = "calendar"
    label: str = ""


@dataclass(frozen=True)
class SchedulableTask:
    id: uuid.UUID
    title: str
    remaining_minutes: int  # effective estimate (after multiplier) minus time already logged
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    importance: int | None = None
    urgency: int | None = None
    deadline: datetime | None = None
    earliest_start: datetime | None = None
    planned_date: date | None = None
    preferred_time: Literal["morning", "afternoon", "evening"] | None = None
    energy: Literal["low", "medium", "high"] | None = None
    project_id: uuid.UUID | None = None
    category: str | None = None
    in_progress: bool = False
    strict_prerequisites: tuple[uuid.UUID, ...] = ()  # unfinished prerequisites
    splittable: bool = True


@dataclass(frozen=True)
class Preferences:
    timezone: str
    workday_start: time
    workday_end: time
    workdays: tuple[int, ...]  # 0=Monday
    buffer_ratio: float
    max_focus_minutes: int
    break_minutes: int
    transition_minutes: int
    min_block_minutes: int
    meals: tuple[tuple[time, time], ...] = ()
    weights: dict[str, float] = field(default_factory=dict)  # scoring weights by factor name


@dataclass(frozen=True)
class HistoricalModel:
    multipliers_by_category: dict[str, float] = field(default_factory=dict)
    multipliers_by_project: dict[uuid.UUID, float] = field(default_factory=dict)
    overall_multiplier: float = 1.0
    focus_quality_by_hour: dict[int, float] = field(default_factory=dict)  # 0..1, observed


@dataclass(frozen=True)
class ScheduledBlock:
    id: uuid.UUID
    kind: BlockKind
    start: datetime
    end: datetime
    task_id: uuid.UUID | None = None
    locked: bool = False
    reasons: tuple["Reason", ...] = ()


@dataclass(frozen=True)
class ScheduleRequest:
    horizon: Interval
    now: datetime
    tasks: tuple[SchedulableTask, ...]
    busy: tuple[BusyInterval, ...]
    fixed_blocks: tuple[ScheduledBlock, ...]
    preferences: Preferences
    history: HistoricalModel


@dataclass(frozen=True)
class Reason:
    factor: str  # e.g. "deadline", "priority", "free_time", "historical_duration", "productive_hours"
    text: str  # human-readable, quoted verbatim by the UI and by Claude
    weight: float = 0.0  # contribution to the task's score (0 for informational reasons)


@dataclass(frozen=True)
class UnscheduledTask:
    task_id: uuid.UUID
    reason: UnscheduledReason
    needed_minutes: int
    detail: str = ""


@dataclass(frozen=True)
class Recommendation:
    action: Literal["move_to_date", "shorten", "drop", "split"]
    task_id: uuid.UUID
    text: str
    target_date: date | None = None


@dataclass(frozen=True)
class CapacityReport:
    available_minutes: int  # free time inside working hours after busy time
    reserved_minutes: int  # buffer, breaks, transitions, meals
    fillable_minutes: int
    required_minutes: int  # work due within / planned for the horizon
    overflow_minutes: int  # max(0, required - fillable)
    recommendations: tuple[Recommendation, ...] = ()

    @property
    def fits(self) -> bool:
        return self.overflow_minutes == 0


@dataclass(frozen=True)
class ScheduleResult:
    blocks: tuple[ScheduledBlock, ...]
    unscheduled: tuple[UnscheduledTask, ...]
    capacity: CapacityReport
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProposedBlock:
    task_id: uuid.UUID
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Violation:
    code: Literal[
        "unknown_task",
        "not_schedulable",
        "non_positive_duration",
        "outside_horizon",
        "calendar_conflict",
        "overlaps_fixed_block",
        "before_earliest_start",
        "after_deadline",
        "dependency_not_met",
    ]
    detail: str


@dataclass(frozen=True)
class TaskOverrun:
    task_id: uuid.UUID
    observed_minutes: int


@dataclass(frozen=True)
class NewBusyInterval:
    interval: BusyInterval


@dataclass(frozen=True)
class BlockSkipped:
    block_id: uuid.UUID


@dataclass(frozen=True)
class TaskFinishedEarly:
    task_id: uuid.UUID


RescheduleEvent = TaskOverrun | NewBusyInterval | BlockSkipped | TaskFinishedEarly


@dataclass(frozen=True)
class BlockChange:
    change: Literal["moved", "shortened", "extended", "dropped", "added"]
    block: ScheduledBlock
    previous: ScheduledBlock | None
    reason: str


@dataclass(frozen=True)
class RescheduleResult:
    blocks: tuple[ScheduledBlock, ...]
    changes: tuple[BlockChange, ...]
    capacity: CapacityReport
