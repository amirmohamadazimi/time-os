# Database schema

SQLAlchemy 2 models in `backend/app/models/`, migrated with Alembic
(`backend/migrations/`). The schema is portable between SQLite (local) and PostgreSQL
(server): UUID primary keys via `sqlalchemy.Uuid`, JSON columns via `sqlalchemy.JSON`,
enums stored as constrained strings, all timestamps UTC.

Status: tables marked **(P1/P2)** exist in the initial migration. Tables marked **(P3/P4)**
are the agreed design and are added by those phases' migrations.

## Plan (concept A)

### `projects` (P1)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | varchar(200) unique | |
| description | text null | |
| color | varchar(16) null | hex colour for the UI |
| status | `active \| archived` | archive instead of delete once history exists |
| created_at, updated_at | timestamptz | |

A project can be deleted only if no task or session references it; otherwise archive it, so
historical analytics never lose their project.

### `tasks` (P1)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| title | varchar(500) | |
| description | text null | |
| project_id | uuid FK projects null, `ON DELETE SET NULL` | indexed |
| category | varchar(100) null | free text with autocomplete (e.g. Programming, German); used for estimation multipliers |
| priority | `low \| medium \| high \| critical` | |
| status | `inbox \| planned \| in_progress \| blocked \| completed \| cancelled` | indexed |
| estimated_minutes | int null, > 0 | user estimate |
| deadline | timestamptz null | hard due moment |
| earliest_start | timestamptz null | do not schedule before |
| planned_date | date null | local day the user intends to work on it (manual planning) |
| preferred_time | `morning \| afternoon \| evening` null | |
| energy_requirement | `low \| medium \| high` null | |
| importance | smallint 1–5 null | |
| urgency | smallint 1–5 null | |
| recurrence_rule | varchar(500) null | RFC 5545 RRULE (`FREQ=WEEKLY;BYDAY=MO,WE`); a task with a rule is a **template** |
| recurrence_parent_id | uuid FK tasks null, `ON DELETE CASCADE` | set on generated occurrences |
| occurrence_date | date null | unique with `recurrence_parent_id` (idempotent generation) |
| tags | json array of strings | |
| source | `user \| ai \| import \| recurrence` | provenance |
| pending_approval | bool | AI-proposed task not yet accepted; excluded from planning |
| completed_at | timestamptz null | set when status becomes `completed` |
| created_at, updated_at | timestamptz | |

Templates are never worked on directly; occurrences are ordinary tasks generated for a date
window (`services/recurrence.py`). Editing a template does not rewrite past occurrences.

### `task_dependencies` (P1)
| Column | Type | Notes |
|---|---|---|
| task_id | uuid FK tasks, `ON DELETE CASCADE` | the dependent task (B) |
| depends_on_id | uuid FK tasks, `ON DELETE CASCADE` | the prerequisite (A) |
| strict | bool | strict ⇒ B cannot be scheduled or started before A is completed |

PK `(task_id, depends_on_id)`, check `task_id <> depends_on_id`. The service rejects cycles.

### `schedules` (P4)
One generated plan for a local date: `id, plan_date, status (proposed | accepted | rejected |
superseded), generated_at, mode (manual | suggest | auto), capacity json, warnings json,
input_fingerprint`.

### `schedule_blocks` (P4)
`id, schedule_id, task_id null, kind (task | break | buffer | meal | review | calendar),
start_time, end_time, state (planned | active | done | skipped | moved), origin
(user | scheduler | ai), locked bool, calendar_event_id null, reasons json, created_at,
updated_at`. Moves are recorded in `audit_log`, which is also the source for
"frequently postponed" analytics.

## Available time (concept B)

### `calendar_accounts` (P3)
`id, provider ('google'), email, scopes, refresh_token_encrypted, access_token_encrypted,
token_expiry, status (connected | expired | revoked), created_at, updated_at`.

### `calendars` (P3)
`id, account_id, provider_calendar_id, summary, timezone, selected bool, sync_token,
last_synced_at, last_error`.

### `calendar_events` (P3)
| Column | Notes |
|---|---|
| id | uuid PK |
| calendar_id | FK calendars |
| provider_event_id | Google event id; unique with `calendar_id` |
| recurring_event_id | master id for expanded recurring instances |
| title, location | |
| start_time, end_time | timestamptz; all-day events stored with `all_day = true` |
| busy | bool from `transparency` (opaque = busy) |
| status | `confirmed \| tentative \| cancelled` (cancelled kept as tombstone) |
| origin | `USER_CREATED_EVENT \| APP_GENERATED_EVENT` |
| schedule_block_id | FK schedule_blocks null (for app-generated blocks) |
| etag, remote_updated_at, synced_at | sync bookkeeping |
| raw | json, original payload |

## Actual behaviour (concept C)

### `focus_sessions` (P1)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| task_id | uuid FK tasks null, `ON DELETE SET NULL` | indexed |
| type | `work \| rest` | |
| state | `running \| paused \| finished` | at most one non-finished session |
| source | `timer \| manual \| import` | |
| start_time | timestamptz | indexed |
| end_time | timestamptz null | null while live |
| tz_offset_minutes | int | local UTC offset at start |
| planned_duration_s | int null | timer target (e.g. 1500) |
| active_duration_s | int null | elapsed − paused, set at finish |
| paused_duration_s | int | accumulated pause time |
| paused_since | timestamptz null | set while paused |
| pause_count | int null | number of pauses (null when unknown, e.g. imports) |
| end_reason | `completed \| stopped \| skipped \| switched \| unknown` null | how the timer ended |
| outcome | `completed \| partial \| blocked \| abandoned` null | user's assessment of task progress |
| notes | text null | |
| tags | json array | |
| task_title_snapshot | varchar(500) null | task title at session start |
| project_id | uuid FK projects null | project **at session start** (snapshot, not live) |
| category_snapshot | varchar(100) null | task category at session start |
| external_id | varchar(200) null | id from the source app; unique with `source` |
| import_batch_id | uuid FK import_batches null | |
| quality_flags | json array | e.g. `long_active`, `long_pause`, `implausible_elapsed`, `zero_length` |
| exclude_from_stats | bool | outliers kept but excluded from metrics |
| voided_at | timestamptz null | soft delete; voided rows are ignored everywhere |
| created_at, updated_at | timestamptz | |

Finished sessions are **immutable history**: their times and durations are never edited.
Only annotations (`notes`, `tags`, `outcome`, `exclude_from_stats`, task/project assignment)
can change, and each change is audited. Snapshots mean renaming or moving a task later
doesn't rewrite what happened.

### `import_batches` (P2)
`id, kind ('focus_sessions'), filename, file_sha256, options json, summary json,
created_at, rolled_back_at`.

### `import_records` (P2)
`id, batch_id FK (cascade), row_number, raw json (original cell values, untouched),
status (imported | duplicate | invalid), errors json, warnings json, session_id FK null`.
Every input row is preserved here, including invalid ones.

## Cross-cutting

### `audit_log` (P1)
`id (bigint autoincrement), at, action (e.g. task.deleted, import.committed), source
(user | ai | scheduler | import | calendar | system), entity_type, entity_id, before json,
after json, reason text`.

### `app_settings` (P1)
Single row (`id = 1`) holding a JSON document validated by the `UserSettings` Pydantic model
(timezone, working hours, scheduling/calendar modes, AI approval, focus defaults, import
thresholds, personalization thresholds). Unknown keys are dropped and missing keys take
defaults, so settings evolve without migrations.

## Indexes

`tasks(status)`, `tasks(project_id)`, `tasks(planned_date)`, `tasks(deadline)`,
`focus_sessions(start_time)`, `focus_sessions(task_id)`, `focus_sessions(state)`,
`audit_log(entity_type, entity_id)`, `audit_log(at)`.
