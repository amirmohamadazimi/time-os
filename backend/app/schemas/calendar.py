import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import CalendarAccountStatus, CalendarEventStatus, CalendarProvider, EventOrigin
from app.schemas.common import ORMModel
from app.schemas.project import HEX_COLOR


class IcalFeedCreate(BaseModel):
    url: str = Field(min_length=10, max_length=2048, description="Secret iCal address; stored encrypted")
    name: str | None = Field(None, min_length=1, max_length=200)
    all_day_busy: bool = False


class CalendarUpdate(BaseModel):
    summary: str | None = Field(None, min_length=1, max_length=200)
    color: str | None = Field(None, pattern=HEX_COLOR)
    selected: bool | None = None
    all_day_busy: bool | None = None


class CalendarOut(ORMModel):
    id: uuid.UUID
    account_id: uuid.UUID
    summary: str
    timezone: str | None
    color: str | None
    selected: bool
    all_day_busy: bool
    last_synced_at: datetime | None
    last_error: str | None


class CalendarAccountOut(ORMModel):
    """Never includes the feed link or tokens: only the host, so the user can tell feeds apart."""

    id: uuid.UUID
    provider: CalendarProvider
    display_name: str
    status: CalendarAccountStatus
    feed_host: str | None
    created_at: datetime
    calendars: list[CalendarOut]


class CalendarEventOut(ORMModel):
    id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    location: str | None
    start_time: datetime
    end_time: datetime
    all_day: bool
    busy: bool
    status: CalendarEventStatus
    origin: EventOrigin
    recurring_event_id: str | None


class SyncResult(BaseModel):
    calendar_id: uuid.UUID
    summary: str
    status: Literal["synced", "not_modified", "skipped", "error"]
    created: int = 0
    updated: int = 0
    cancelled: int = 0
    unchanged: int = 0
    skipped_components: int = 0
    truncated: bool = False
    error: str | None = None


class TimeSpan(BaseModel):
    start: datetime
    end: datetime
    minutes: int


class BusySpan(TimeSpan):
    titles: list[str]


class FreeTime(BaseModel):
    date: date
    working_day: bool
    window_start: datetime | None
    window_end: datetime | None
    busy: list[BusySpan]
    free: list[TimeSpan]
    busy_minutes: int
    free_minutes: int
    calendars: int
    synced_at: datetime | None = Field(description="oldest successful sync among selected calendars")
