"""Local-time helpers. Storage is UTC; 'days' are local days in the user's timezone."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def local_date(at: datetime, tz: ZoneInfo) -> date:
    return at.astimezone(tz).date()


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day, in UTC (DST-safe: days may be 23 or 25 hours)."""
    start = datetime.combine(day, time(0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def offset_minutes(tz: ZoneInfo, at: datetime) -> int:
    offset = at.astimezone(tz).utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0
