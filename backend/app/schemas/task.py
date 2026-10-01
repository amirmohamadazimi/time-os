import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import Energy, Priority, TaskSource, TaskStatus, TimeOfDay
from app.schemas.common import ORMModel, Tags, UTCDatetime


class DependencyIn(BaseModel):
    depends_on_id: uuid.UUID
    strict: bool = True


class DependencyOut(ORMModel):
    depends_on_id: uuid.UUID
    strict: bool


class _TaskFields(BaseModel):
    description: str | None = Field(None, max_length=20000)
    project_id: uuid.UUID | None = None
    category: str | None = Field(None, max_length=100)
    estimated_minutes: int | None = Field(None, gt=0, le=10000)
    deadline: UTCDatetime | None = None
    earliest_start: UTCDatetime | None = None
    planned_date: date | None = None
    preferred_time: TimeOfDay | None = None
    energy_requirement: Energy | None = None
    importance: int | None = Field(None, ge=1, le=5)
    urgency: int | None = Field(None, ge=1, le=5)
    recurrence_rule: str | None = Field(None, max_length=500, description="RFC 5545 RRULE, e.g. FREQ=DAILY")


class TaskCreate(_TaskFields):
    title: str = Field(min_length=1, max_length=500)
    priority: Priority = Priority.medium
    status: TaskStatus = TaskStatus.inbox
    tags: Tags = Field(default_factory=list)
    dependencies: list[DependencyIn] = Field(default_factory=list)


class TaskUpdate(_TaskFields):
    """Partial update: only fields present in the request body are changed."""

    title: str | None = Field(None, min_length=1, max_length=500)
    priority: Priority | None = None
    status: TaskStatus | None = None
    tags: Tags | None = None
    dependencies: list[DependencyIn] | None = None


class InboxCapture(BaseModel):
    text: str = Field(min_length=1, max_length=20000, description="One task per line; bullets are stripped")


class RecurrenceWindow(BaseModel):
    start_date: date
    end_date: date


class TaskOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None
    project_id: uuid.UUID | None
    category: str | None
    priority: Priority
    status: TaskStatus
    estimated_minutes: int | None
    deadline: datetime | None
    earliest_start: datetime | None
    planned_date: date | None
    preferred_time: TimeOfDay | None
    energy_requirement: Energy | None
    importance: int | None
    urgency: int | None
    recurrence_rule: str | None
    recurrence_parent_id: uuid.UUID | None
    occurrence_date: date | None
    tags: list[str]
    source: TaskSource
    pending_approval: bool
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    dependencies: list[DependencyOut]
    is_template: bool
    blocked_by: list[uuid.UUID] = Field(default_factory=list, description="unfinished strict prerequisites")
    actual_minutes: float = Field(0, description="focus time logged on this task")
