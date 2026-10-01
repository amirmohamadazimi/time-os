"""Read-only calendar feeds (secret iCal address): parsing, sync, privacy and free time."""

import io
import os
import stat
import urllib.error
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path

import pytest
from sqlalchemy import select

from app import crypto
from app.api.calendar import get_feed_fetcher
from app.calendar import ical
from app.config import Config
from app.models import AuditEntry, CalendarAccount, CalendarEvent
from tests.conftest import ok

FEED = (Path(__file__).parent / "fixtures" / "google_calendar.ics").read_bytes()
URL = "https://calendar.example.com/calendar/ical/me%40example.com/private-abc123/basic.ics"
NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


class FakeFeed:
    """Stands in for the HTTP fetch; records the conditional headers it was given."""

    def __init__(self, body: bytes = FEED, etag: str | None = '"v1"'):
        self.body = body
        self.etag = etag
        self.calls: list[tuple[str, str | None, str | None]] = []
        self.error: ical.FeedError | None = None

    def __call__(self, url, etag, last_modified):
        self.calls.append((url, etag, last_modified))
        if self.error:
            raise self.error
        if etag and etag == self.etag:
            return ical.FetchResult(None, etag, last_modified)
        return ical.FetchResult(self.body, self.etag, None)


@pytest.fixture
def feed(client, monkeypatch):
    monkeypatch.setattr(ical, "_check_public_host", lambda host, port: None)  # no DNS in tests
    fake = FakeFeed()
    client.app.dependency_overrides[get_feed_fetcher] = lambda: fake
    ok(client.put("/api/settings", json={"timezone": "Asia/Tehran"}))
    return fake


def connect(client, **extra):
    return ok(client.post("/api/calendar/ical", json={"url": URL, **extra}), 201)


def parse(body: bytes = FEED) -> dict[str, ical.FeedEvent]:
    start, end = ical.window(NOW)
    feed = ical.parse_feed(body, window_start=start, window_end=end, default_timezone="Asia/Tehran")
    return {e.provider_event_id: e for e in feed.events}


def test_parse_expands_recurrence_and_reads_busy_signals():
    events = parse()
    standups = sorted(k for k in events if k.startswith("standup@google.com_"))
    # Six weekly occurrences, one removed by EXDATE, one moved by an override.
    assert standups == [
        "standup@google.com_20261005T060000Z",
        "standup@google.com_20261019T060000Z",
        "standup@google.com_20261026T060000Z",
        "standup@google.com_20261102T060000Z",
        "standup@google.com_20261109T060000Z",
    ]
    moved = events["standup@google.com_20261019T060000Z"]
    assert moved.title == "Standup (moved)" and moved.start == datetime(2026, 10, 19, 7, 30, tzinfo=UTC)
    assert moved.recurring_event_id == "standup@google.com"

    assert events["dentist@google.com"].start == datetime(2026, 10, 1, 10, 30, tzinfo=UTC)
    assert events["dentist@google.com"].location == "Clinic"
    assert events["dentist@google.com"].is_busy(all_day_busy=False)
    assert not events["lunch@google.com"].is_busy(False)  # "show as available"
    assert events["review@google.com"].declined and not events["review@google.com"].is_busy(False)
    assert events["cancelled@google.com"].status == "cancelled"
    holiday = events["holiday@google.com"]
    assert holiday.all_day and holiday.start == datetime(2026, 10, 1, 20, 30, tzinfo=UTC)  # local midnight
    assert not holiday.is_busy(False) and holiday.is_busy(True)
    assert events["flight@google.com"].start == datetime(2026, 10, 3, 6, 0, tzinfo=UTC)
    # Floating time (no timezone) uses the feed's timezone.
    assert events["gym@google.com"].start == datetime(2026, 10, 1, 14, 30, tzinfo=UTC)
    assert "old@google.com" not in events  # outside the sync window


def test_rejects_non_calendar_content():
    with pytest.raises(ical.FeedError, match="iCal"):
        parse(b"<html>Sign in</html>")


@pytest.mark.parametrize(
    "url",
    [
        "http://calendar.example.com/basic.ics",
        "ftp://x/y.ics",
        "https://127.0.0.1/basic.ics",
        "https://localhost/basic.ics",
        "https://10.1.2.3/basic.ics",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_feed_urls_must_be_public_https(url):
    with pytest.raises(ical.FeedError):
        ical.validate_feed_url(url)


def test_webcal_links_are_accepted(monkeypatch):
    monkeypatch.setattr(ical, "_check_public_host", lambda host, port: None)
    assert (
        ical.validate_feed_url(" webcal://calendar.example.com/a.ics ")
        == "https://calendar.example.com/a.ics"
    )


def test_connect_stores_link_encrypted_and_never_returns_it(client, feed, db):
    account = connect(client)
    assert URL not in str(account)
    assert account["display_name"] == "me@example.com" and account["feed_host"] == "calendar.example.com"
    [calendar] = account["calendars"]
    assert calendar["timezone"] == "Asia/Tehran" and calendar["last_synced_at"] is not None
    assert URL not in str(ok(client.get("/api/calendar/accounts")))

    row = db.scalar(select(CalendarAccount))
    assert URL not in row.feed_url_encrypted and crypto.decrypt(row.feed_url_encrypted) == URL
    audits = list(db.scalars(select(AuditEntry).where(AuditEntry.action == "calendar.connected")))
    assert len(audits) == 1 and "private-abc123" not in str(audits[0].after)
    # Descriptions are not stored: only what planning needs.
    assert "Private agenda" not in str([e.raw for e in db.scalars(select(CalendarEvent))])

    assert ok(client.post("/api/calendar/ical", json={"url": URL}), 409)["error"]["code"] == "conflict"


def test_events_and_free_time(client, feed):
    connect(client)
    events = ok(client.get("/api/calendar/events", params={"from": "2026-10-01", "to": "2026-10-01"}))
    titles = [e["title"] for e in events]
    assert titles == ["Declined review", "Lunch with a friend", "Dentist", "Overlapping call", "Gym"]
    assert {e["origin"] for e in events} == {"USER_CREATED_EVENT"}
    with_cancelled = client.get(
        "/api/calendar/events", params={"from": "2026-10-01", "to": "2026-10-01", "include_cancelled": True}
    )
    assert "Cancelled meeting" in [e["title"] for e in ok(with_cancelled)]

    free = ok(client.get("/api/calendar/free-time", params={"date": "2026-10-01"}))
    assert free["working_day"] and free["calendars"] == 1
    # Working hours 08:30–18:00 Tehran; only Dentist + the overlapping call block time (14:00–15:30).
    assert [(b["start"], b["end"], b["titles"]) for b in free["busy"]] == [
        ("2026-10-01T10:30:00Z", "2026-10-01T12:00:00Z", ["Dentist", "Overlapping call"])
    ]
    assert [f["minutes"] for f in free["free"]] == [330, 150]
    assert free["busy_minutes"] == 90 and free["free_minutes"] == 480

    saturday = ok(client.get("/api/calendar/free-time", params={"date": "2026-10-03"}))
    assert not saturday["working_day"] and saturday["free"] == []


def test_sync_is_idempotent_and_revalidates(client, feed):
    connect(client)
    [first] = ok(client.post("/api/calendar/sync"))
    assert first["status"] == "not_modified"  # same ETag
    assert feed.calls[-1][1] == '"v1"'

    feed.etag = '"v2"'
    [second] = ok(client.post("/api/calendar/sync"))
    assert second["status"] == "synced" and second["created"] == 0 and second["updated"] == 0
    assert second["unchanged"] == 13

    [skipped] = ok(client.post("/api/calendar/sync", params={"max_age_s": 900}))
    assert skipped["status"] == "skipped"
    [forced] = ok(client.post("/api/calendar/sync", params={"max_age_s": 900, "force": True}))
    assert forced["status"] == "synced" and feed.calls[-1][1] is None


def test_changed_and_removed_events(client, feed, db):
    connect(client)
    body = FEED.replace(b"SUMMARY:Flight", b"SUMMARY:Flight to Shiraz")
    start = body.index(b"BEGIN:VEVENT\r\nDTSTART;TZID=Asia/Tehran:20261001T140000")
    end = body.index(b"END:VEVENT\r\n", start) + len(b"END:VEVENT\r\n")
    feed.body, feed.etag = body[:start] + body[end:], '"v2"'

    [result] = ok(client.post("/api/calendar/sync"))
    assert (result["created"], result["updated"], result["cancelled"]) == (0, 1, 1)
    dentist = db.scalar(select(CalendarEvent).where(CalendarEvent.provider_event_id == "dentist@google.com"))
    assert dentist.status == "cancelled" and not dentist.busy  # tombstone, not deleted
    free = ok(client.get("/api/calendar/free-time", params={"date": "2026-10-01"}))
    assert free["busy_minutes"] == 60  # only the overlapping call is left
    saturday = ok(client.get("/api/calendar/events", params={"from": "2026-10-03", "to": "2026-10-03"}))
    assert [e["title"] for e in saturday] == ["Flight to Shiraz"]


def test_all_day_events_block_time_only_when_enabled(client, feed):
    calendar_id = connect(client)["calendars"][0]["id"]
    friday = {"date": "2026-10-02"}
    assert ok(client.get("/api/calendar/free-time", params=friday))["busy_minutes"] == 0
    updated = ok(client.patch(f"/api/calendar/calendars/{calendar_id}", json={"all_day_busy": True}))
    assert updated["all_day_busy"]
    blocked = ok(client.get("/api/calendar/free-time", params=friday))
    assert blocked["free_minutes"] == 0 and blocked["busy"][0]["titles"] == ["Holiday"]

    ok(client.patch(f"/api/calendar/calendars/{calendar_id}", json={"selected": False}))
    assert ok(client.get("/api/calendar/events", params={"from": "2026-10-01", "to": "2026-10-31"})) == []


def test_failed_sync_keeps_the_cache(client, feed):
    connect(client)
    feed.error = ical.FeedError("the calendar link no longer works (it may have been reset)")
    [result] = ok(client.post("/api/calendar/sync", params={"force": True}))
    assert result["status"] == "error" and "no longer works" in result["error"]
    [calendar] = ok(client.get("/api/calendar/accounts"))[0]["calendars"]
    assert "no longer works" in calendar["last_error"]
    assert len(ok(client.get("/api/calendar/events", params={"from": "2026-10-01", "to": "2026-10-01"}))) == 5


def test_bad_link_stores_nothing(client, feed, db):
    feed.body = b"<html>not a calendar</html>"
    response = client.post("/api/calendar/ical", json={"url": URL})
    assert response.status_code == 422 and response.json()["error"]["code"] == "calendar_feed_error"
    assert db.scalar(select(CalendarAccount)) is None


def test_changed_secret_key_asks_to_reconnect(client, feed, monkeypatch):
    connect(client)
    monkeypatch.setattr(crypto, "get_config", lambda: Config(secret_key="a-different-key"))
    [result] = ok(client.post("/api/calendar/sync", params={"force": True}))
    assert result["status"] == "error" and "reconnect" in result["error"]
    assert ok(client.get("/api/calendar/accounts"))[0]["status"] == "error"


def test_disconnect_removes_link_and_events(client, feed, db):
    account_id = connect(client)["id"]
    ok(client.delete(f"/api/calendar/accounts/{account_id}"), 204)
    assert ok(client.get("/api/calendar/accounts")) == []
    assert db.scalar(select(CalendarEvent)) is None
    entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "calendar.disconnected"))
    assert entry.before["cached_events"] == 13 and "feed_url_encrypted" not in entry.before


def test_generated_key_file(tmp_path):
    config = Config(secret_key=None, secret_key_file=str(tmp_path / "data" / "secret.key"))
    token = crypto.encrypt("hello", config)
    key_file = tmp_path / "data" / "secret.key"
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert crypto.decrypt(token, config) == "hello"  # the same key is read back


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "status", Message(), io.BytesIO(b""))


class _Response(io.BytesIO):
    headers = {"ETag": '"abc"', "Last-Modified": "Thu, 01 Oct 2026 08:00:00 GMT"}


def test_fetch_feed_maps_http_results(monkeypatch):
    monkeypatch.setattr(ical, "_check_public_host", lambda host, port: None)
    outcomes: list = []

    class Opener:
        def open(self, request, timeout):
            assert URL not in str(request.headers)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(ical.urllib.request, "build_opener", lambda *handlers: Opener())
    outcomes.append(_Response(FEED))
    result = ical.fetch_feed(URL)
    assert result.body == FEED and result.etag == '"abc"'
    outcomes.append(_http_error(304))
    assert ical.fetch_feed(URL, etag='"abc"').body is None
    outcomes.append(_http_error(404))
    with pytest.raises(ical.FeedError, match="no longer works") as excinfo:
        ical.fetch_feed(URL)
    assert URL not in str(excinfo.value)
    outcomes.append(_Response(b"x" * (ical.FEED_MAX_BYTES + 1)))
    with pytest.raises(ical.FeedError, match="larger than"):
        ical.fetch_feed(URL)


def test_redirects_are_checked_like_the_original_link(monkeypatch):
    checked = []
    monkeypatch.setattr(ical, "_check_public_host", lambda host, port: checked.append(host))
    handler = ical._CheckedRedirect()
    request = ical.urllib.request.Request(URL)
    follow = handler.redirect_request(
        request, None, 302, "Found", Message(), "https://cdn.example.com/basic.ics"
    )
    assert follow.full_url == "https://cdn.example.com/basic.ics" and checked == ["cdn.example.com"]
    with pytest.raises(ical.FeedError, match="https"):
        handler.redirect_request(request, None, 302, "Found", Message(), "http://cdn.example.com/basic.ics")
