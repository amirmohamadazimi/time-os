# Focus sessions

Focus sessions are the **actual behaviour** domain: what really happened, kept separate from the
plan (tasks) and from available time (calendar). Code: `backend/app/services/focus.py` (live timer),
`backend/app/services/sessions.py` (history), `backend/app/models/focus.py`.

## The live timer is server-authoritative

```
start ──► running ──pause──► paused ──resume──► running
             │                  │
             └──── finish ──────┴──► finished (immutable history)
```

- At most **one** session is live (running or paused). Starting a second one returns `409`;
  use **switch** instead.
- The server stores `start_time`, `paused_since` and the accumulated `paused_duration_s`. Nothing
  depends on the browser staying open: a refresh, a closed tab or a second device sees the same state.
- `GET /api/focus/current` returns the session plus `server_time` and `active_so_far_s`. The UI ticks
  the display locally from that snapshot, correcting for the difference between the browser and server
  clocks (`frontend/src/lib/timer.ts`), and re-syncs every 30 s.
- Every service function takes `now` explicitly, so tests drive time with a fake clock.

## Durations

```
elapsed = end_time − start_time
paused  = sum of all pauses (capped at elapsed)
active  = elapsed − paused
```

`active_duration_s` is what analytics counts as focus time. Pauses are kept separately, along with
`pause_count`, so interruptions can be measured.

## Ending a session

| Action | `end_reason` | Notes |
|---|---|---|
| Finish | `completed` | Optionally records `outcome` and can mark the task done |
| Stop | `stopped` | Ended early |
| Skip | `skipped` | Mainly for breaks |
| Switch | `switched` | Ends the current session and starts one on another task in one step. The target is validated first, so a rejected switch changes nothing. |
| Discard | (deleted) | For a session started by mistake; recorded in the audit log |
| Imported | `unknown` | When the export carried neither a completed nor a stopped flag |

`outcome` (the "How did it go?" prompt) is one of `completed`, `partial`, `blocked`, `abandoned`.
Finishing with `blocked` moves an open task to `blocked`. A zero-length session is flagged
`zero_length` and excluded from analytics.

## Rules for starting work on a task

`tasks.ensure_workable` is shared by the timer, the scheduler and Claude's tools. A task cannot be
worked on when it is:

- a recurring **template** (work on one of its occurrences instead),
- `completed` or `cancelled`,
- an **AI proposal** still awaiting approval,
- waiting on an unfinished **strict** prerequisite.

Starting a work session moves the task to `in_progress`. Rest sessions never link to a task.

## Snapshots

Each session copies the task title, project and category at start (`task_title_snapshot`,
`project_id`, `category_snapshot`). History and analytics stay correct when a task is renamed, moved
or deleted (`task_id` is set to `NULL`, the snapshot remains).

## Time zones

Timestamps are stored in UTC. Each session also stores `tz_offset_minutes`, the user's UTC offset
when it started. Local hour and weekday are computed as `start_time + tz_offset_minutes`, so a
morning session stays a morning session after travel or a DST change.

## History is immutable

Finished sessions never change their times or durations. These can change, and each change is audited:

- `notes`, `tags`, `outcome`
- `exclude_from_stats` (hide an implausible session from analytics without deleting it)
- `task_id` / `project_id` (re-attribute a session; rest sessions cannot be linked to tasks)

Deleting a session sets `voided_at` (a soft delete recorded in the audit log). It disappears from
history and analytics.

## Manual sessions

`POST /api/sessions` logs a session after the fact (`source = manual`). The end must be after the
start, the end cannot be in the future, the pause must be shorter than the session, and it must not
overlap another session (`409`).

## Provenance

`source` is `timer`, `manual` or `import`. Imported sessions also carry `external_id`,
`import_batch_id` and `quality_flags`; see [csv-import.md](csv-import.md).
