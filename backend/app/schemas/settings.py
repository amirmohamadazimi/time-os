from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore")


class WorkingHours(_Section):
    start: time = time(8, 30)
    end: time = time(18, 0)
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], description="0=Monday … 6=Sunday")

    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError("working_hours.end must be after start")
        if any(d < 0 or d > 6 for d in self.days):
            raise ValueError("working_hours.days must be 0..6")
        self.days = sorted(set(self.days))
        return self


class TimeWindow(_Section):
    label: str = Field(max_length=50)
    start: time
    end: time


class FocusDefaults(_Section):
    work_minutes: int = Field(50, ge=5, le=240)
    break_minutes: int = Field(10, ge=1, le=120)


class SchedulerPreferences(_Section):
    buffer_ratio: float = Field(0.15, ge=0, le=0.6)
    max_focus_minutes: int = Field(90, ge=15, le=240)
    break_minutes: int = Field(15, ge=0, le=60)
    transition_minutes: int = Field(5, ge=0, le=30)
    min_block_minutes: int = Field(25, ge=5, le=120)
    meals: list[TimeWindow] = Field(
        default_factory=lambda: [TimeWindow(label="Lunch", start=time(12, 0), end=time(13, 0))]
    )


class ImportRules(_Section):
    long_active_minutes: int = Field(240, ge=30)
    long_pause_minutes: int = Field(120, ge=5)
    implausible_elapsed_hours: int = Field(16, ge=2)
    duplicate_tolerance_seconds: int = Field(60, ge=0, le=3600)


class Personalization(_Section):
    min_samples: int = Field(5, ge=1, description="below this, estimates are not adjusted")
    strong_samples: int = Field(20, ge=1, description="at or above this, adjustment is considered strong")
    prior_strength: float = Field(10.0, gt=0, description="shrinkage: weight = n / (n + prior_strength)")
    min_multiplier: float = Field(0.5, gt=0)
    max_multiplier: float = Field(3.0, gt=0)


class UserSettings(_Section):
    timezone: str = "UTC"
    working_hours: WorkingHours = Field(default_factory=WorkingHours)
    scheduling_mode: Literal["manual", "suggest", "auto"] = "suggest"
    calendar_mode: Literal["read_only", "suggest", "auto_create"] = "read_only"
    require_approval_for_ai_tasks: bool = True
    focus: FocusDefaults = Field(default_factory=FocusDefaults)
    scheduler: SchedulerPreferences = Field(default_factory=SchedulerPreferences)
    import_rules: ImportRules = Field(default_factory=ImportRules)
    personalization: Personalization = Field(default_factory=Personalization)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {v}") from exc
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
