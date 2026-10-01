"""Calendar cache: connect read-only iCal feeds, sync them, and answer events / free-time queries.

Events from feeds are always ``USER_CREATED_EVENT`` and are never written back anywhere: an iCal
feed is read-only by nature. Sync is idempotent (upsert on ``(calendar_id, provider_event_id)``),
and events that disappear from the feed inside the sync window become ``cancelled`` tombstones.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import crypto
from app.calendar import ical
from app.errors import ConflictError, NotFoundError
from app.models import Calendar, CalendarAccount, CalendarEvent
from app.models.enums import (
    ActionSource,
    CalendarAccountStatus,
    CalendarEventStatus,
    CalendarProvider,
    EventOrigin,
)
from app.scheduler.types import BusyInterval
from app.schemas.calendar import (
    BusySpan,
    CalendarUpdate,
    FreeTime,
    IcalFeedCreate,
    SyncResult,
    TimeSpan,
)
from app.schemas.settings import UserSettings
from app.services import audit
from app.timeutil import day_bounds_utc

SYNC_PAST_DAYS = 30
SYNC_FUTURE_DAYS = 90


# --- Accounts and calendars ---------------------------------------------------------------------


def list_accounts(db: Session) -> list[CalendarAccount]:
    stmt = (
        select(CalendarAccount)
        .options(selectinload(CalendarAccount.calendars))
        .order_by(CalendarAccount.created_at)
    )
    return list(db.scalars(stmt))


def get_account(db: Session, account_id: uuid.UUID) -> CalendarAccount:
    account = db.get(CalendarAccount, account_id)
    if account is None:
        raise NotFoundError(f"calendar account {account_id} not found")
    return account


def get_calendar(db: Session, calendar_id: uuid.UUID) -> Calendar:
    calendar = db.get(Calendar, calendar_id)
    if calendar is None:
        raise NotFoundError(f"calendar {calendar_id} not found")
    return calendar


def _public(account: CalendarAccount) -> dict:
    """Audit snapshot without the encrypted link."""
    data = audit.snapshot(account)
    data.pop("feed_url_encrypted", None)
    return data


def add_ical_feed(
    db: Session,
    data: IcalFeedCreate,
    *,
    settings: UserSettings,
    now: datetime,
    fetcher: ical.Fetcher = ical.fetch_feed,
) -> CalendarAccount:
    url = ical.validate_feed_url(data.url)
    fingerprint = ical.url_fingerprint(url)
    if db.scalar(select(CalendarAccount.id).where(CalendarAccount.feed_url_sha256 == fingerprint)):
        raise ConflictError("this calendar link is already connected")
    fetched = fetcher(url, None, None)
    if fetched.body is None:
        raise ical.FeedError("the calendar server returned no content")
    feed = _parse(fetched.body, settings, now)  # validates before anything is stored

    host = ical.feed_host(url)
    summary = data.name or feed.name or host
    account = CalendarAccount(
        provider=CalendarProvider.ical,
        display_name=summary,
        status=CalendarAccountStatus.connected,
        feed_url_encrypted=crypto.encrypt(url),
        feed_url_sha256=fingerprint,
        feed_host=host,
    )
    calendar = Calendar(
        account=account,
        provider_calendar_id="feed",
        summary=summary,
        timezone=feed.timezone,
        selected=True,
        all_day_busy=data.all_day_busy,
    )
    db.add(account)
    db.flush()
    audit.record(
        db,
        action="calendar.connected",
        source=ActionSource.user,
        entity_type="calendar_account",
        entity_id=account.id,
        after=_public(account),
    )
    _apply(db, calendar, feed, fetched, now)
    db.commit()
    db.refresh(account)
    return account


def delete_account(db: Session, account_id: uuid.UUID) -> None:
    """Disconnect: removes the stored link, its calendars and their cached events."""
    account = get_account(db, account_id)
    calendar_ids = [c.id for c in account.calendars]
    events = (
        db.scalar(select(func.count()).where(CalendarEvent.calendar_id.in_(calendar_ids)))
        if calendar_ids
        else 0
    )
    audit.record(
        db,
        action="calendar.disconnected",
        source=ActionSource.user,
        entity_type="calendar_account",
        entity_id=account.id,
        before={**_public(account), "cached_events": events},
    )
    db.delete(account)
    db.commit()


def update_calendar(db: Session, calendar_id: uuid.UUID, data: CalendarUpdate) -> Calendar:
    calendar = get_calendar(db, calendar_id)
    changes = data.model_dump(exclude_unset=True)
    for key in ("summary", "selected", "all_day_busy"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    before = audit.snapshot(calendar)
    for key, value in changes.items():
        setattr(calendar, key, value)
    if "all_day_busy" in changes:
        for event in db.scalars(
            select(CalendarEvent).where(
                CalendarEvent.calendar_id == calendar.id, CalendarEvent.all_day.is_(True)
            )
        ):
            event.busy = _busy_from_raw(event, calendar.all_day_busy)
    db.flush()
    old, new = audit.diff(before, audit.snapshot(calendar))
    if new:
        audit.record(
            db,
            action="calendar.updated",
            source=ActionSource.user,
            entity_type="calendar",
            entity_id=calendar.id,
            before=old,
            after=new,
        )
    db.commit()
    return calendar


def _busy_from_raw(event: CalendarEvent, all_day_busy: bool) -> bool:
    raw = event.raw or {}
    return (
        event.status != CalendarEventStatus.cancelled
        and not raw.get("transparent", False)
        and not raw.get("declined", False)
        and (all_day_busy or not event.all_day)
    )


# --- Sync ---------------------------------------------------------------------------------------


def _parse(body: bytes, settings: UserSettings, now: datetime) -> ical.Feed:
    start, end = ical.window(now, SYNC_PAST_DAYS, SYNC_FUTURE_DAYS)
    return ical.parse_feed(body, window_start=start, window_end=end, default_timezone=settings.timezone)


@dataclass
class _Counts:
    created: int = 0
    updated: int = 0
    cancelled: int = 0
    unchanged: int = 0


def _apply(
    db: Session, calendar: Calendar, feed: ical.Feed, fetched: ical.FetchResult, now: datetime
) -> _Counts:
    counts = _Counts()
    window_start, window_end = ical.window(now, SYNC_PAST_DAYS, SYNC_FUTURE_DAYS)
    rows = db.scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == calendar.id))
    existing = {e.provider_event_id: e for e in rows}
    seen: set[str] = set()
    for item in feed.events:
        seen.add(item.provider_event_id)
        row = existing.get(item.provider_event_id)
        if row is not None and row.etag == item.etag:
            counts.unchanged += 1
            continue
        if row is None:
            row = CalendarEvent(calendar_id=calendar.id, provider_event_id=item.provider_event_id)
            db.add(row)
            counts.created += 1
        else:
            counts.updated += 1
        row.recurring_event_id = item.recurring_event_id
        row.title = item.title
        row.location = item.location
        row.start_time = item.start
        row.end_time = item.end
        row.all_day = item.all_day
        row.status = CalendarEventStatus(item.status)
        row.busy = item.is_busy(calendar.all_day_busy)
        row.origin = EventOrigin.user_created
        row.etag = item.etag
        row.remote_updated_at = item.remote_updated_at
        row.synced_at = now
        row.raw = {"timezone": item.timezone, "transparent": item.transparent, "declined": item.declined}
    if not feed.truncated:  # a cut-off feed cannot prove that an event was removed
        for provider_id, row in existing.items():
            if (
                provider_id not in seen
                and row.status != CalendarEventStatus.cancelled
                and row.start_time < window_end
                and row.end_time > window_start
            ):
                row.status = CalendarEventStatus.cancelled
                row.busy = False
                row.synced_at = now
                counts.cancelled += 1
    calendar.sync_token = fetched.etag
    calendar.http_last_modified = fetched.last_modified
    calendar.last_synced_at = now
    calendar.last_error = None
    if feed.timezone and not calendar.timezone:
        calendar.timezone = feed.timezone
    calendar.account.status = CalendarAccountStatus.connected
    return counts


def sync_calendar(
    db: Session,
    calendar: Calendar,
    *,
    settings: UserSettings,
    now: datetime,
    fetcher: ical.Fetcher = ical.fetch_feed,
    force: bool = False,
) -> SyncResult:
    account = calendar.account
    result = SyncResult(calendar_id=calendar.id, summary=calendar.summary, status="synced")
    if account.provider != CalendarProvider.ical or not account.feed_url_encrypted:
        return result.model_copy(update={"status": "skipped"})
    try:
        url = crypto.decrypt(account.feed_url_encrypted)
        fetched = fetcher(
            url, None if force else calendar.sync_token, None if force else calendar.http_last_modified
        )
        if fetched.body is None:
            calendar.last_synced_at = now
            calendar.last_error = None
            db.commit()
            return result.model_copy(update={"status": "not_modified"})
        feed = _parse(fetched.body, settings, now)
    except crypto.SecretUnreadable as exc:
        account.status = CalendarAccountStatus.error
        return _failed(db, calendar, result, exc.message)
    except ical.FeedError as exc:
        return _failed(db, calendar, result, exc.message)
    counts = _apply(db, calendar, feed, fetched, now)
    try:
        db.commit()
    except IntegrityError:  # another request synced the same calendar at the same moment
        db.rollback()
        return result.model_copy(update={"status": "skipped"})
    return result.model_copy(
        update={
            "created": counts.created,
            "updated": counts.updated,
            "cancelled": counts.cancelled,
            "unchanged": counts.unchanged,
            "skipped_components": feed.skipped,
            "truncated": feed.truncated,
        }
    )


def _failed(db: Session, calendar: Calendar, result: SyncResult, message: str) -> SyncResult:
    """Keep the cache as it was and record why, so the UI can show it and planning can flag stale data."""
    calendar.last_error = message[:1000]
    db.commit()
    return result.model_copy(update={"status": "error", "error": message})


def sync_all(
    db: Session,
    *,
    settings: UserSettings,
    now: datetime,
    fetcher: ical.Fetcher = ical.fetch_feed,
    calendar_id: uuid.UUID | None = None,
    max_age_s: int | None = None,
    force: bool = False,
) -> list[SyncResult]:
    """Sync selected calendars (or one). ``max_age_s`` skips calendars synced more recently than that."""
    if calendar_id is not None:
        calendars = [get_calendar(db, calendar_id)]
    else:
        calendars = list(
            db.scalars(select(Calendar).where(Calendar.selected.is_(True)).order_by(Calendar.summary))
        )
    results = []
    for calendar in calendars:
        fresh = (
            max_age_s is not None
            and calendar.last_synced_at is not None
            and calendar.last_error is None
            and now - calendar.last_synced_at < timedelta(seconds=max_age_s)
        )
        if fresh and not force:
            results.append(SyncResult(calendar_id=calendar.id, summary=calendar.summary, status="skipped"))
            continue
        results.append(sync_calendar(db, calendar, settings=settings, now=now, fetcher=fetcher, force=force))
    return results


# --- Queries ------------------------------------------------------------------------------------


def _events_between(
    db: Session, start: datetime, end: datetime, *, include_cancelled: bool = False, busy_only: bool = False
) -> list[CalendarEvent]:
    stmt = (
        select(CalendarEvent)
        .join(Calendar, CalendarEvent.calendar_id == Calendar.id)
        .where(Calendar.selected.is_(True), CalendarEvent.start_time < end, CalendarEvent.end_time > start)
        .order_by(CalendarEvent.start_time, CalendarEvent.title)
    )
    if not include_cancelled:
        stmt = stmt.where(CalendarEvent.status != CalendarEventStatus.cancelled)
    if busy_only:
        stmt = stmt.where(CalendarEvent.busy.is_(True))
    return list(db.scalars(stmt))


def list_events(
    db: Session, settings: UserSettings, from_date: date, to_date: date, include_cancelled: bool = False
) -> list[CalendarEvent]:
    tz = ZoneInfo(settings.timezone)
    start, _ = day_bounds_utc(from_date, tz)
    _, end = day_bounds_utc(to_date, tz)
    return _events_between(db, start, end, include_cancelled=include_cancelled)


def _busy_spans(db: Session, start: datetime, end: datetime) -> list[tuple[datetime, datetime, list[str]]]:
    events = _events_between(db, start, end, busy_only=True)
    return _merge([(max(e.start_time, start), min(e.end_time, end), e.title) for e in events])


def busy_intervals(db: Session, start: datetime, end: datetime) -> list[BusyInterval]:
    """Busy calendar time in [start, end), clipped and merged; the scheduler's calendar input."""
    return [
        BusyInterval(start=s, end=e, source="calendar", label=", ".join(titles))
        for s, e, titles in _busy_spans(db, start, end)
    ]


def _merge(spans: list[tuple[datetime, datetime, str]]) -> list[tuple[datetime, datetime, list[str]]]:
    merged: list[tuple[datetime, datetime, list[str]]] = []
    for start, end, title in sorted(spans, key=lambda s: (s[0], s[1])):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            last_start, last_end, titles = merged[-1]
            merged[-1] = (last_start, max(last_end, end), titles if title in titles else [*titles, title])
        else:
            merged.append((start, end, [title]))
    return merged


def _minutes(start: datetime, end: datetime) -> int:
    return round((end - start).total_seconds() / 60)


def free_time(db: Session, settings: UserSettings, day: date) -> FreeTime:
    """Working hours on ``day`` minus busy calendar events. Meals and other protected time are the
    scheduler's concern and are not subtracted here."""
    tz = ZoneInfo(settings.timezone)
    selected = list(db.scalars(select(Calendar).where(Calendar.selected.is_(True))))
    synced = [c.last_synced_at for c in selected if c.last_synced_at is not None]
    working_day = day.weekday() in settings.working_hours.days
    window_start = datetime.combine(day, settings.working_hours.start, tzinfo=tz)
    window_end = datetime.combine(day, settings.working_hours.end, tzinfo=tz)
    busy = _busy_spans(db, window_start, window_end) if working_day else []
    free: list[TimeSpan] = []
    cursor = window_start
    if working_day:
        for start, end, _ in busy:
            if start > cursor:
                free.append(TimeSpan(start=cursor, end=start, minutes=_minutes(cursor, start)))
            cursor = max(cursor, end)
        if cursor < window_end:
            free.append(TimeSpan(start=cursor, end=window_end, minutes=_minutes(cursor, window_end)))
    busy_spans = [BusySpan(start=s, end=e, minutes=_minutes(s, e), titles=titles) for s, e, titles in busy]
    return FreeTime(
        date=day,
        working_day=working_day,
        window_start=window_start if working_day else None,
        window_end=window_end if working_day else None,
        busy=busy_spans,
        free=free,
        busy_minutes=sum(b.minutes for b in busy_spans),
        free_minutes=sum(f.minutes for f in free),
        calendars=len(selected),
        synced_at=min(synced) if synced else None,
    )
