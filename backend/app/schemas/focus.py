import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import EndReason, Outcome, SessionSource, SessionState, SessionType
from app.schemas.common import ORMModel, Tags, UTCDatetime


class FocusStart(BaseModel):
    task_id: uuid.UUID | None = None
    type: SessionType = SessionType.work
    planned_duration_s: int | None = Field(None, ge=60, le=8 * 3600)
    notes: str | None = Field(None, max_length=5000)
    tags: Tags = Field(default_factory=list)


class FocusFinish(BaseModel):
    end_reason: Literal["completed", "stopped", "skipped"] = "completed"
    outcome: Outcome | None = None
    notes: str | None = Field(None, max_length=5000)
    tags: Tags | None = None
    complete_task: bool = Field(False, description="also mark the session's task as completed")


class FocusSwitch(BaseModel):
    task_id: uuid.UUID
    type: SessionType = SessionType.work
    planned_duration_s: int | None = Field(None, ge=60, le=8 * 3600)


class FocusAnnotate(BaseModel):
    notes: str | None = Field(None, max_length=5000)
    tags: Tags | None = None


class ManualSessionCreate(BaseModel):
    task_id: uuid.UUID | None = None
    type: SessionType = SessionType.work
    start_time: UTCDatetime
    end_time: UTCDatetime
    paused_duration_s: int = Field(0, ge=0)
    end_reason: EndReason = EndReason.completed
    outcome: Outcome | None = None
    notes: str | None = Field(None, max_length=5000)
    tags: Tags = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_times(self):
        elapsed = (self.end_time - self.start_time).total_seconds()
        if elapsed <= 0:
            raise ValueError("end_time must be after start_time")
        if self.paused_duration_s >= elapsed:
            raise ValueError("paused_duration_s must be shorter than the session")
        return self


class SessionAnnotate(BaseModel):
    """Annotations only: times and durations of finished sessions are immutable."""

    notes: str | None = Field(None, max_length=5000)
    tags: Tags | None = None
    outcome: Outcome | None = None
    exclude_from_stats: bool | None = None
    task_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None


class FocusSessionOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    task_title_snapshot: str | None
    project_id: uuid.UUID | None
    category_snapshot: str | None
    type: SessionType
    state: SessionState
    source: SessionSource
    start_time: datetime
    end_time: datetime | None
    tz_offset_minutes: int
    planned_duration_s: int | None
    active_duration_s: int | None
    paused_duration_s: int
    paused_since: datetime | None
    pause_count: int | None
    elapsed_s: int | None
    end_reason: EndReason | None
    outcome: Outcome | None
    completed: bool
    stopped: bool
    notes: str | None
    tags: list[str]
    external_id: str | None
    import_batch_id: uuid.UUID | None
    quality_flags: list[str]
    exclude_from_stats: bool
    voided_at: datetime | None
    created_at: datetime


class LiveSessionOut(FocusSessionOut):
    server_time: datetime
    active_so_far_s: int = Field(description="active seconds at server_time (excludes pauses)")
