# API specification

REST + JSON under `/api`. The live OpenAPI document is served at `/api/openapi.json` and the
interactive docs at `/api/docs`; this file is the human-readable contract.

Conventions

* Timestamps are ISO 8601 with offset (responses are always UTC, `...Z`). Requests with a
  naive timestamp are rejected with `422`.
* Dates (`planned_date`, analytics `from`/`to`) are local calendar dates in the user's timezone.
* Durations are integer **seconds** (`*_s`) or **minutes** (`*_minutes`) as named.
* IDs are UUIDs.
* Errors: `{"error": {"code": "not_found" | "conflict" | "validation_error" | "unauthorized" | "unavailable", "message": "...", "details": ...}}`
  with status 404 / 409 / 422 / 401 / 503.
* Auth: when `TIMEOS_API_TOKEN` is set, send `Authorization: Bearer <token>`.

## Health
| Method | Path | Response |
|---|---|---|
| GET | `/api/health` | `{status, db: "ok" \| "down", version}` |

## Projects
| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/projects` | `?status=active\|archived` | `Project[]` |
| POST | `/api/projects` | `ProjectCreate {name, description?, color?}` | `201 Project` |
| GET | `/api/projects/{id}` | | `Project` |
| PATCH | `/api/projects/{id}` | `ProjectUpdate` (any field, incl. `status`) | `Project` |
| DELETE | `/api/projects/{id}` | | `204`; `409` if tasks or sessions reference it (archive instead) |
| GET | `/api/projects/{id}/stats` | | `ProjectStats {total_focus_minutes, session_count, tasks_completed, tasks_remaining, estimated_remaining_minutes, last_worked_at}` |

## Tasks
`Task` = all columns from the schema plus `dependencies: [{depends_on_id, strict}]`,
`is_template`, `blocked_by: uuid[]` (unfinished strict prerequisites) and
`actual_minutes` (sum of focus time logged on the task).

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/tasks` | `?status=` (repeatable) `&project_id&category&tag&q&planned_date&due_before&pending_approval&include_templates=false&limit=200&offset=0` | `Task[]` |
| POST | `/api/tasks` | `TaskCreate` | `201 Task` |
| POST | `/api/tasks/inbox` | `{text}`: one task per non-empty line, bullets stripped | `201 Task[]` (status `inbox`) |
| GET | `/api/tasks/categories` | | `string[]` |
| GET | `/api/tasks/{id}` | | `Task` |
| PATCH | `/api/tasks/{id}` | `TaskUpdate` (partial; `dependencies` replaces the set) | `Task` |
| DELETE | `/api/tasks/{id}` | | `204` (sessions keep their snapshot; audited) |
| POST | `/api/tasks/{id}/complete` | | `Task` |
| POST | `/api/tasks/{id}/approve` | | `Task` (clears `pending_approval`) |
| GET | `/api/tasks/{id}/sessions` | | `FocusSession[]` |
| POST | `/api/tasks/recurrences/generate` | `{start_date, end_date}` | `Task[]` newly created occurrences (idempotent) |

`TaskCreate`: `title` (required), `description, project_id, category, priority, status,
estimated_minutes, deadline, earliest_start, planned_date, preferred_time,
energy_requirement, importance, urgency, recurrence_rule, tags, dependencies`.
Validation: RRULE must parse; dependencies must exist and not create a cycle;
`earliest_start <= deadline`; status `completed` sets `completed_at`.

## Focus timer (live session)
`FocusSession` = schema columns plus derived `elapsed_s`, `completed`, `stopped`
(booleans mirroring the external export format), and `server_time` on live responses.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/focus/current` | | `FocusSession \| null` |
| POST | `/api/focus/start` | `{task_id?, type: work\|rest, planned_duration_s?, notes?, tags?}` | `201 FocusSession`; `409` if a session is live or the task is blocked by a strict dependency |
| POST | `/api/focus/pause` | | `FocusSession`; `409` unless running |
| POST | `/api/focus/resume` | | `FocusSession`; `409` unless paused |
| PATCH | `/api/focus/current` | `{notes?, tags?}` | `FocusSession` |
| POST | `/api/focus/finish` | `{end_reason: completed\|stopped\|skipped, outcome?, notes?, tags?, complete_task?: bool}` | `FocusSession` (finished) |
| POST | `/api/focus/switch` | `{task_id, type?, planned_duration_s?}` | `FocusSession` (the new one; previous ends with `switched`) |
| DELETE | `/api/focus/current` | | `204`: discards a session started by mistake (audited) |

## Sessions (history)
| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/sessions` | `?from&to&type&task_id&project_id&tag&q&source&include_excluded=true&limit=100&offset=0` | `{items: FocusSession[], total}` |
| POST | `/api/sessions` | `ManualSession {task_id?, type, start_time, end_time, paused_duration_s?, end_reason?, outcome?, notes?, tags?}` | `201 FocusSession` (`source=manual`) |
| GET | `/api/sessions/{id}` | | `FocusSession` |
| PATCH | `/api/sessions/{id}` | `{notes?, tags?, outcome?, exclude_from_stats?, task_id?, project_id?}` (annotations only) | `FocusSession` |
| DELETE | `/api/sessions/{id}` | | `204` (soft void, audited) |

## Imports
| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/api/imports/focus-sessions` | multipart `file`; query `dry_run=true\|false`, `default_timezone?`, `duration_unit=auto\|seconds\|milliseconds\|minutes` | `ImportReport` |
| GET | `/api/imports` | | `ImportBatch[]` |
| GET | `/api/imports/{id}` | | `ImportBatch` (with summary) |
| GET | `/api/imports/{id}/records` | `?status=imported\|duplicate\|invalid&limit&offset` | `{items: ImportRecord[], total}` |
| DELETE | `/api/imports/{id}` | | `ImportBatch`: rolls back (voids the batch's sessions, audited) |

`ImportReport`: `{batch_id | null (dry run), dry_run, summary, issues[]}` where `summary` =
`{rows_read, valid, duplicates, invalid, flagged, excluded_from_stats, work_sessions,
rest_sessions, total_focus_hours, total_rest_hours, avg_work_session_minutes,
median_work_session_minutes, first_session, last_session, duration_unit,
assumed_timezone_rows, warnings_by_code, errors_by_code}` and `issues` = up to 500
`{row_number, status, errors[], warnings[], raw}`.

## Analytics (observed statistics)
Common query: `from`, `to` (local dates, inclusive), `type=work|rest` (default `work`),
`project_id`, `tag`. Every response carries `meta: {kind: "observed", from, to,
session_count, excluded_count}`.

| Method | Path | Response |
|---|---|---|
| GET | `/api/analytics/summary` | totals, average/median/longest session, counts by end reason, completion and interruption rates, task completion rate |
| GET | `/api/analytics/timeseries` | `?granularity=day\|week\|month` → `[{period, focus_minutes, sessions}]` |
| GET | `/api/analytics/by-hour` | 24 rows: `{hour, focus_minutes, sessions_started, avg_session_minutes, completion_rate}` |
| GET | `/api/analytics/by-weekday` | 7 rows: `{weekday, focus_minutes, avg_daily_focus_minutes, sessions, avg_session_minutes, completion_rate}` |
| GET | `/api/analytics/by-project` | `[{project_id, project_name, focus_minutes, share, sessions}]` |
| GET | `/api/analytics/by-tag` | `[{tag, focus_minutes, share, sessions}]` |
| GET | `/api/analytics/gaps` | `{avg_gap_minutes, median_gap_minutes, samples}` time between consecutive same-day work sessions |
| GET | `/api/analytics/estimation` | `?group_by=category\|project` → `[{group, samples, avg_estimate_minutes, avg_actual_minutes, ratio, median_ratio, multiplier, confidence}]` |
| GET | `/api/analytics/patterns` | `[{id, kind: "observed", statement, values, sample_size}]` deterministic findings |

## Dashboard
| Method | Path | Response |
|---|---|---|
| GET | `/api/dashboard/today` | `{date, timezone, focused_minutes, rest_minutes, planned_minutes, sessions_today, current_session, next_tasks[], due_today[], overdue[], inbox_count, pending_approval_count}` |

`planned_minutes` is the remaining estimate of tasks planned for or due today until the
Phase 4 scheduler supplies schedule blocks; `next_tasks` is ordered by deadline, then
priority, then importance.

## Settings and audit
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/settings` | | `UserSettings` |
| PUT | `/api/settings` | `UserSettings` (partial merge) | `UserSettings` |
| GET | `/api/audit` | `?entity_type&entity_id&action&limit=100` | `AuditEntry[]` |

## Calendar
Read-only iCal feeds ([google-calendar.md](google-calendar.md)). The feed link is write-only: no
response ever contains it.

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/calendar/accounts` | | `CalendarAccount[]` (with `calendars`, `feed_host`, never the link) |
| POST | `/api/calendar/ical` | `{url, name?, all_day_busy?}` | `201 CalendarAccount`; fetched and synced first, `422 calendar_feed_error` if the link fails, `409` if already connected |
| DELETE | `/api/calendar/accounts/{id}` | | `204`; removes the link, calendars and cached events (audited) |
| PATCH | `/api/calendar/calendars/{id}` | `{summary?, color?, selected?, all_day_busy?}` | `Calendar` |
| POST | `/api/calendar/sync` | `?calendar_id&max_age_s&force` | `SyncResult[]` (`synced \| not_modified \| skipped \| error` with counts) |
| GET | `/api/calendar/events` | `?from&to` (local dates, ≤ 366 days), `include_cancelled` | `CalendarEvent[]` from selected calendars |
| GET | `/api/calendar/free-time` | `?date` | `FreeTime`: working hours minus busy events, merged busy spans with titles, oldest `synced_at` |

## Planned endpoints (later phases)

| Phase | Endpoints |
|---|---|
| 3 Calendar (OAuth) | `GET /api/calendar/oauth/start`, `GET /api/calendar/oauth/callback` |
| 4 Scheduler | `POST /api/schedules/generate {date}`, `GET /api/schedules/{date}`, `POST /api/schedules/{id}/accept\|reject`, `PATCH /api/schedule-blocks/{id}`, `POST /api/schedules/{id}/reschedule {event}`, `GET /api/schedule-blocks/{id}/explain` |
| 5 Claude | `POST /api/chat` (SSE stream of text + tool-call events), `GET /api/chat/tools`, `GET /api/reviews/daily?date`, `GET /api/reviews/weekly?week` |
