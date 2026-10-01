"""Read-only calendar feeds in iCalendar format (RFC 5545).

Google Calendar's "Secret address in iCal format" is the main use: it needs no Google Cloud project,
but it can only be read. The link is a credential, so callers store it encrypted and never log it.

Fetching is a plain HTTPS GET with ETag / Last-Modified revalidation. Parsing expands recurring
events (RRULE, RDATE, EXDATE, moved or cancelled instances) inside a window with
``recurring_ical_events``, so each occurrence becomes one cached event with a stable id.
"""

import hashlib
import ipaddress
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import icalendar
import recurring_ical_events

from app.errors import DomainError

FEED_MAX_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT_S = 20
MAX_INSTANCES = 5000
USER_AGENT = "TimeOS calendar sync (read-only)"

EventStatus = Literal["confirmed", "tentative", "cancelled"]


class FeedError(DomainError):
    code = "calendar_feed_error"
    status_code = 422


@dataclass(frozen=True)
class FetchResult:
    body: bytes | None  # None when the server answered 304 Not Modified
    etag: str | None = None
    last_modified: str | None = None


Fetcher = Callable[[str, str | None, str | None], FetchResult]


@dataclass(frozen=True)
class FeedEvent:
    provider_event_id: str
    recurring_event_id: str | None
    title: str
    location: str | None
    start: datetime  # aware, UTC
    end: datetime
    all_day: bool
    status: EventStatus
    transparent: bool  # TRANSP:TRANSPARENT ("show as available")
    declined: bool  # the calendar owner declined the invitation
    timezone: str | None
    remote_updated_at: datetime | None
    etag: str

    def is_busy(self, all_day_busy: bool) -> bool:
        return (
            self.status != "cancelled"
            and not self.transparent
            and not self.declined
            and (all_day_busy or not self.all_day)
        )


@dataclass(frozen=True)
class Feed:
    name: str | None
    timezone: str | None
    events: list[FeedEvent]
    skipped: int  # components without a usable start time
    truncated: bool  # more than MAX_INSTANCES occurrences in the window


# --- URL handling -------------------------------------------------------------------------------


def validate_feed_url(url: str) -> str:
    """Normalise and check a feed link: HTTPS only, and never an internal address.

    The server fetches this URL, so internal targets (localhost, private networks, cloud metadata
    at 169.254.169.254) are refused.
    """
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise FeedError("the calendar link must start with https:// (or webcal://)")
    if len(url) > 2048:
        raise FeedError("the calendar link is too long")
    _check_public_host(parts.hostname, parts.port or 443)
    return url


def _check_public_host(host: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FeedError(f"cannot find the calendar server {host}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise FeedError("calendar links to local or private network addresses are not allowed")


def feed_host(url: str) -> str:
    return urlsplit(url).hostname or ""


def url_fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to targets that pass the same checks (a redirect could point inside)."""

    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_feed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_feed(url: str, etag: str | None = None, last_modified: str | None = None) -> FetchResult:
    """GET the feed. Raises FeedError with a message the user can act on; never includes the URL."""
    validate_feed_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/calendar, */*;q=0.5"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    opener = urllib.request.build_opener(_CheckedRedirect)
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_S) as response:
            body = response.read(FEED_MAX_BYTES + 1)
            if len(body) > FEED_MAX_BYTES:
                raise FeedError(f"the calendar is larger than {FEED_MAX_BYTES // (1024 * 1024)} MB")
            return FetchResult(body, response.headers.get("ETag"), response.headers.get("Last-Modified"))
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return FetchResult(None, etag, last_modified)
        if exc.code in (401, 403, 404, 410):
            raise FeedError(
                "the calendar link no longer works (it may have been reset); copy it again and reconnect"
            ) from None
        raise FeedError(f"the calendar server answered HTTP {exc.code}; try again later") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FeedError(f"cannot reach the calendar server ({type(reason).__name__})") from None


# --- Parsing ------------------------------------------------------------------------------------


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _to_utc(value: date | datetime, tz: ZoneInfo) -> datetime:
    if not isinstance(value, datetime):  # all-day: local midnight
        value = datetime.combine(value, time(0), tzinfo=tz)
    elif value.tzinfo is None or value.utcoffset() is None:  # floating time
        value = value.replace(tzinfo=tz)
    return value.astimezone(UTC)


def _instance_stamp(value: date | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(UTC)
        return value.strftime("%Y%m%dT%H%M%SZ")
    return value.strftime("%Y%m%d")


def _text(component, name: str, limit: int) -> str | None:
    value = component.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _owner_declined(component, owner_email: str | None) -> bool:
    if not owner_email:
        return False
    attendees = component.get("ATTENDEE")
    if attendees is None:
        return False
    if not isinstance(attendees, list):
        attendees = [attendees]
    for attendee in attendees:
        email = str(attendee).removeprefix("mailto:").removeprefix("MAILTO:").lower()
        if email == owner_email and str(attendee.params.get("PARTSTAT", "")).upper() == "DECLINED":
            return True
    return False


def _status(component) -> EventStatus:
    value = str(component.get("STATUS", "")).upper()
    return {"CANCELLED": "cancelled", "TENTATIVE": "tentative"}.get(value, "confirmed")  # type: ignore[return-value]


def parse_feed(
    body: bytes,
    *,
    window_start: datetime,
    window_end: datetime,
    default_timezone: str,
) -> Feed:
    """Expand the feed's events that overlap [window_start, window_end) into occurrences."""
    try:
        calendar = icalendar.Calendar.from_ical(body)
    except Exception as exc:  # the parser raises ValueError, KeyError, … on malformed input
        raise FeedError("this link did not return a calendar in iCal format") from exc
    if calendar.name != "VCALENDAR":
        raise FeedError("this link did not return a calendar in iCal format")

    name = _text(calendar, "X-WR-CALNAME", 200)
    feed_tz_name = _text(calendar, "X-WR-TIMEZONE", 64)
    feed_tz = _zone(feed_tz_name) or ZoneInfo(default_timezone)
    # Google names the primary calendar after its owner's address; used to spot declined invitations.
    owner_email = name.lower() if name and "@" in name and " " not in name else None

    series: dict[str, int] = {}
    for component in calendar.walk("VEVENT"):
        uid = str(component.get("UID", ""))
        recurring = component.get("RRULE") is not None or component.get("RDATE") is not None
        series[uid] = series.get(uid, 0) + (2 if recurring else 1)
    recurring_uids = {uid for uid, weight in series.items() if uid and weight > 1}

    query = recurring_ical_events.of(calendar, skip_bad_series=True)
    events: dict[str, FeedEvent] = {}
    skipped = 0
    truncated = False
    try:
        occurrences = query.between(window_start, window_end)
    except Exception as exc:
        raise FeedError("the calendar contains recurrence rules that cannot be read") from exc
    for component in occurrences:
        if len(events) >= MAX_INSTANCES:
            truncated = True
            break
        try:
            raw_start = component.start
            raw_end = component.end
        except Exception:
            skipped += 1
            continue
        tzid = component.get("DTSTART").params.get("TZID") if component.get("DTSTART") else None
        tz = _zone(tzid) or feed_tz
        all_day = not isinstance(raw_start, datetime)
        start = _to_utc(raw_start, ZoneInfo(default_timezone) if all_day else tz)
        end = _to_utc(raw_end, ZoneInfo(default_timezone) if all_day else tz)
        if end < start:
            end = start

        uid = str(component.get("UID", "")).strip()
        title = _text(component, "SUMMARY", 500) or "(no title)"
        if not uid:  # invalid per RFC 5545, but seen in the wild: derive a stable id
            uid = "nouid-" + hashlib.sha256(f"{title}|{start.isoformat()}".encode()).hexdigest()[:16]
        if uid in recurring_uids:
            rid = component.get("RECURRENCE-ID")
            stamp = _instance_stamp(rid.dt if rid is not None else raw_start)
            provider_id, recurring_id = f"{uid}_{stamp}", uid
        else:
            provider_id, recurring_id = uid, None
        if provider_id in events:
            continue

        location = _text(component, "LOCATION", 500)
        status = _status(component)
        transparent = str(component.get("TRANSP", "")).upper() == "TRANSPARENT"
        declined = _owner_declined(component, owner_email)
        modified = component.get("LAST-MODIFIED")
        remote_updated = _to_utc(modified.dt, UTC) if modified is not None else None
        fingerprint = "|".join(
            [title, location or "", start.isoformat(), end.isoformat(), str(all_day), status]
            + [str(transparent), str(declined)]
        )
        events[provider_id] = FeedEvent(
            provider_event_id=provider_id,
            recurring_event_id=recurring_id,
            title=title,
            location=location,
            start=start,
            end=end,
            all_day=all_day,
            status=status,
            transparent=transparent,
            declined=declined,
            timezone=str(tzid) if tzid else feed_tz_name,
            remote_updated_at=remote_updated,
            etag=hashlib.sha256(fingerprint.encode()).hexdigest()[:32],
        )
    return Feed(
        name=name, timezone=feed_tz_name, events=list(events.values()), skipped=skipped, truncated=truncated
    )


def window(now: datetime, past_days: int = 30, future_days: int = 90) -> tuple[datetime, datetime]:
    return now - timedelta(days=past_days), now + timedelta(days=future_days)
