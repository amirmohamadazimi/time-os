import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, Now, Settings
from app.calendar import ical
from app.errors import ValidationFailed
from app.schemas.calendar import (
    CalendarAccountOut,
    CalendarEventOut,
    CalendarOut,
    CalendarUpdate,
    FreeTime,
    IcalFeedCreate,
    SyncResult,
)
from app.services import calendar as calendars

router = APIRouter(prefix="/calendar", tags=["calendar"])


def get_feed_fetcher() -> ical.Fetcher:
    """The HTTP client for iCal feeds. Overridden in tests with a fake."""
    return ical.fetch_feed


@router.get("/accounts", response_model=list[CalendarAccountOut])
def list_accounts(db: DB):
    return calendars.list_accounts(db)


@router.post("/ical", response_model=CalendarAccountOut, status_code=status.HTTP_201_CREATED)
def connect_ical(
    db: DB,
    settings: Settings,
    now: Now,
    body: IcalFeedCreate,
    fetcher: ical.Fetcher = Depends(get_feed_fetcher),
):
    return calendars.add_ical_feed(db, body, settings=settings, now=now, fetcher=fetcher)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(db: DB, account_id: uuid.UUID):
    calendars.delete_account(db, account_id)


@router.patch("/calendars/{calendar_id}", response_model=CalendarOut)
def update_calendar(db: DB, calendar_id: uuid.UUID, body: CalendarUpdate):
    return calendars.update_calendar(db, calendar_id, body)


@router.post("/sync", response_model=list[SyncResult])
def sync(
    db: DB,
    settings: Settings,
    now: Now,
    calendar_id: uuid.UUID | None = None,
    max_age_s: int | None = Query(None, ge=0, le=86400, description="skip calendars synced this recently"),
    force: bool = False,
    fetcher: ical.Fetcher = Depends(get_feed_fetcher),
):
    return calendars.sync_all(
        db,
        settings=settings,
        now=now,
        fetcher=fetcher,
        calendar_id=calendar_id,
        max_age_s=max_age_s,
        force=force,
    )


@router.get("/events", response_model=list[CalendarEventOut])
def list_events(
    db: DB,
    settings: Settings,
    from_: date = Query(alias="from"),
    to: date = Query(),
    include_cancelled: bool = False,
):
    if to < from_:
        raise ValidationFailed("'to' must not be before 'from'")
    if (to - from_).days > 366:
        raise ValidationFailed("at most 366 days per request")
    return calendars.list_events(db, settings, from_, to, include_cancelled)


@router.get("/free-time", response_model=FreeTime)
def free_time(db: DB, settings: Settings, day: date = Query(alias="date")):
    return calendars.free_time(db, settings, day)
