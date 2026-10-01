# Google Calendar integration (Phase 3)

Two ways to connect, sharing one local cache (`calendar_accounts` → `calendars` → `calendar_events`):

| | Secret iCal address (implemented) | OAuth (designed below) |
|---|---|---|
| Setup | Paste one link from Google Calendar settings | Google Cloud project + OAuth client |
| Read events and busy time | yes | yes |
| Write focus blocks | no (the feed is read-only) | with `calendar_mode` = `suggest` or `auto_create` |
| Sync | full feed, revalidated with ETag / Last-Modified | incremental with `nextSyncToken` |

## Secret iCal address (read-only, implemented)

Google Calendar → Settings → *Settings for my calendars* → a calendar → *Integrate calendar* →
**Secret address in iCal format**. Any iCalendar (RFC 5545) feed over HTTPS works the same way.

* **The link is a credential.** It is encrypted at rest (`app/crypto.py`: Fernet, key derived with
  HKDF from `TIMEOS_SECRET_KEY`, or from a random key generated once into `TIMEOS_SECRET_KEY_FILE`).
  The API never returns it; responses and audit entries show only the host. A SHA-256 of the link
  detects the same link being connected twice. If the key changes, sync reports "reconnect" and the
  account is marked `error`; the cache stays readable.
* **Fetching** (`app/calendar/ical.py`): HTTPS only (`webcal://` is rewritten), and hosts that resolve
  to loopback, private, link-local or reserved addresses are refused because the server makes the
  request. Redirects are not followed, the body is capped at 10 MB, and the timeout is 20 s. Error
  messages never include the link. `If-None-Match` / `If-Modified-Since` make unchanged feeds cheap.
* **Parsing**: `icalendar` + `recurring_ical_events` expand RRULE, RDATE, EXDATE and moved or
  cancelled instances inside the sync window (30 days back, 90 ahead; at most 5,000 occurrences).
  Instance ids follow Google's shape, `<UID>_<original start in UTC>`, so a moved occurrence keeps its
  id. Times with a `TZID` use it, floating times use the feed's `X-WR-TIMEZONE`, and all-day events
  start at local midnight in the user's timezone. Descriptions and attendee lists are not stored.
* **Busy**: not busy when `TRANSP:TRANSPARENT`, `STATUS:CANCELLED`, or when the calendar owner
  declined (Google names the primary calendar after its owner's address, which is matched against
  `ATTENDEE;PARTSTAT=DECLINED`). All-day events block time only when the calendar's
  `all_day_busy` is on.
* **Sync**: upsert on `(calendar_id, provider_event_id)`; a fingerprint of the stored fields detects
  changes. Events missing from the feed inside the window become `cancelled` tombstones (skipped when
  the feed was truncated). A failed fetch keeps the cache and records `last_error`. The UI syncs when
  a calendar view opens if the last sync is older than 15 minutes; *Sync now* forces it. There is no
  background job, so a host that sleeps when idle (Render free) still works.
* Every event from a feed is `USER_CREATED_EVENT`: nothing is ever written back.

Endpoints are listed in [api.md](api.md#calendar). Free time (`GET /api/calendar/free-time`) is working
hours minus busy events; meals and protected time are left to the scheduler, which reads
`services.calendar.busy_intervals()` as its calendar input.

# OAuth design

```
Google Calendar API ──► Calendar sync service ──► calendar_events (local cache) ──► Scheduler
        ▲                                                                            │
        └──────── generated focus blocks (only with permission) ◄──── schedule_blocks ┘
```

## OAuth

* Authorization-code flow with PKCE, run entirely by the backend
  (`/api/calendar/oauth/start` → Google consent → `/api/calendar/oauth/callback`).
  `state` is a signed, single-use value bound to the browser session.
* Scopes: `https://www.googleapis.com/auth/calendar.readonly` by default. The write scope
  `calendar.events` is requested only when the user switches `calendar_mode` to `suggest` or
  `auto_create`, through incremental authorization.
* Refresh and access tokens are encrypted at rest (Fernet, key from `TIMEOS_SECRET_KEY`).
  Access tokens are refreshed shortly before expiry; a refresh failure (`invalid_grant`)
  marks the account `expired` and the UI asks the user to reconnect. The rest of the app keeps
  working from the cache.

## Reading and sync

* Per selected calendar, an initial full sync of a window (default: 30 days back, 90 days
  ahead) with `singleEvents=true`, so recurring events arrive as expanded instances that carry
  `recurringEventId`.
* Incremental sync uses the calendar's `nextSyncToken`; a `410 Gone` response clears the token
  and triggers a full resync of the window.
* Upsert key is `(calendar_id, provider_event_id)`, which makes repeated syncs idempotent
  (no duplicates). Changes are detected via `etag`.
* Cancelled events are kept as tombstones with `status = cancelled` so a deleted meeting frees
  its time without losing history.
* Event times are stored in UTC; the event's own timezone is kept in `raw`. All-day events
  are stored with `all_day = true` and only block time if the user opts in.
* Busy/free comes from `transparency` (`opaque` = busy) and attendee response
  (declined = not busy).
* API errors: `429` and `5xx` back off exponentially with jitter (max 5 attempts);
  quota errors stop the sync and record `last_error`. Each sync records `last_synced_at`,
  which the scheduler surfaces when the cache is stale.

## Writing: user events vs app events

Every event has an `origin`:

| Origin | How it's identified | What the app may do |
|---|---|---|
| `USER_CREATED_EVENT` | anything without the app's marker | read only, never modified or deleted automatically |
| `APP_GENERATED_EVENT` | `extendedProperties.private.timeos_block_id` and `timeos_origin=app` | create, update, delete, reschedule, according to `calendar_mode` |

* `read_only` (default): no writes.
* `suggest`: the user confirms each create/update/delete of a generated block.
* `auto_create`: the app writes generated blocks automatically; every write is audited.

Before any update or delete the service re-reads the event and refuses unless the private
marker is present, so a user-created event can never be modified even if local data is wrong.
If the user edits a generated event in Google (moves it), the next sync treats the new time as
a user decision: the block becomes `locked` and the scheduler plans around it.

## Testing

All Google calls go through a small `CalendarClient` interface; tests use a fake built from
recorded JSON responses covering token refresh, `410` resync, recurring instances,
cancellations, timezone changes, duplicate syncs and rate-limit retries.
