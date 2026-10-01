# Google Calendar integration (Phase 3 design)

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
