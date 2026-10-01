# Architecture

Time OS is a **deterministic productivity engine with Claude as its reasoning and
conversational layer**. The application must stay fully useful with AI switched off.

## 1. The three separate concepts

Everything in the system belongs to exactly one of three domains. They are stored in
separate tables and joined only by analytics and the scheduler.

| Concept | Question | Tables | Writers |
|---|---|---|---|
| **A. Plan** | What did I intend to do? | `projects`, `tasks`, `task_dependencies`, `schedules`, `schedule_blocks` | user, AI (as proposals), scheduler |
| **B. Available time** | What time did I actually have? | `calendar_events` (+ working hours / meals in settings) | Google Calendar sync, user |
| **C. Actual behaviour** | What did I actually do? | `focus_sessions`, `import_batches`, `import_records` | focus timer, manual log, CSV importer |

`Plan → Available time → Actual behaviour → Results` is computed by the analytics
engine (estimation accuracy, planned-vs-actual, completion), and its outputs
(multipliers, productive hours) feed back into the scheduler as the *historical model*.

```
            ┌──────────── feedback: multipliers, productive hours ───────────┐
            ▼                                                                 │
  A. Plan ──────► Scheduler (deterministic) ──► Schedule blocks ──► Focus timer ──► C. Sessions
            ▲            ▲                                                    │
  B. Calendar ───────────┘                                                    ▼
                                                                    Analytics engine
```

## 2. Layering

```
 React UI ─┐
           ├──► REST API (FastAPI routers: parsing, auth, HTTP errors only)
 Claude ───┘        │
 (tool layer)       ▼
               Application services  ◄── the only place business rules live
               (tasks, focus, importer, analytics, scheduler, calendar sync, audit)
                    │
                    ▼
               SQLAlchemy models ──► SQLite (local) / PostgreSQL (server)
                                 ──► Google Calendar API (Phase 3)
```

Rules that keep this honest:

* **Routers are thin.** They validate input (Pydantic), call one service function, and map
  domain errors to HTTP. No business logic in routers or React components.
* **Services take `now` explicitly.** Nothing reads the wall clock below the API layer, so
  every time-dependent rule is testable with a fixed clock.
* **Pure cores.** The CSV parser, analytics metrics and the scheduler are pure functions over
  plain data (dataclasses / DataFrames). The DB-facing service wraps them.
* **Claude never touches the database.** It calls tools in `app/ai/tools.py`; each tool
  validates its input with Pydantic and calls the same service functions as the REST API, so
  AI actions go through identical validation (see [claude-tools.md](claude-tools.md)).
* **The database and deterministic services are the source of truth.** Claude output is
  advisory text or a validated tool call, never stored as fact. Observed statistics and AI
  interpretation are labelled separately in every response (`kind: "observed"` vs
  `kind: "ai_interpretation"`).

## 3. Backend (`backend/`)

| Module | Responsibility |
|---|---|
| `app/main.py` | App factory, router registration, error handlers, startup migrations |
| `app/config.py` | Environment configuration (`TIMEOS_*` variables) |
| `app/db.py` | Engine/session, `UTCDateTime` column type, SQLite pragmas |
| `app/models/` | ORM models (one file per domain) |
| `app/schemas/` | Pydantic request/response contracts |
| `app/services/` | Tasks, projects, recurrence, focus timer, sessions, dashboard, settings, audit |
| `app/importer/` | CSV parsing (pure) and import persistence |
| `app/analytics/` | Session DataFrame, metrics, estimation model, observed patterns |
| `app/scheduler/` | Scheduler interface (Phase 4 engine lives here) |
| `app/ai/` | Claude tool registry (Phase 5 adds the provider client and context builder) |
| `app/api/` | FastAPI routers |

Stack: Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, pandas, python-dateutil.

### Time and timezones

* Every timestamp is stored as **UTC** (`UTCDateTime` rejects naive datetimes on write and
  returns aware UTC datetimes on read, on both SQLite and PostgreSQL).
* Each focus session also stores `tz_offset_minutes`: the UTC offset of the user's local
  time **when the session started**. Hour-of-day and weekday analytics use
  `start_time + tz_offset`, so data recorded while travelling or across DST changes keeps its
  true local hour.
* "Today", day buckets and `planned_date` use the user's configured IANA timezone
  (`settings.timezone`). A session belongs to the local day it started on.

## 4. Frontend (`frontend/`)

React 18 + TypeScript + Vite, Mantine UI components, TanStack Query for server state,
React Router, `@mantine/charts` (Recharts) for analytics.

```
src/
  api/        typed client (one function per endpoint) + shared types
  hooks/      useFocusTimer (server-authoritative timer with clock-skew correction)
  pages/      Dashboard, Tasks, Projects, Focus, Sessions, Import, Analytics, Settings
  components/ presentational pieces (TaskForm, TimerDisplay, StatCard, ...)
  lib/        formatting helpers (durations, dates)
```

The UI holds no business state: the timer's authoritative state lives on the server, so a
browser refresh or a second tab never loses a running session.

## 5. Local-first deployment

Everything runs on the user's machine: `docker compose up` starts the API (with SQLite in a
named volume) and the UI. No cloud dependency is required except Google Calendar (Phase 3)
and Claude (Phase 5), both optional. The same images run on a server with PostgreSQL via
`docker-compose.postgres.yml`.

## 6. Failure behaviour

| Failure | Behaviour |
|---|---|
| Claude unavailable / no API key | Chat and AI explanations are disabled with a clear message; every other feature works. |
| Google Calendar unavailable | Scheduler uses the local `calendar_events` cache and reports its `synced_at` age. |
| Database unavailable | `/api/health` reports `db: down`; requests fail with `503` and a JSON error, never a stack trace. |
| Corrupt import rows | Row is recorded as `invalid` with error codes; the rest of the file imports. |

## 7. Security and authentication

Time OS is single-user and single-tenant: one database per person.

* **Local mode (default):** the API listens on localhost only. No login.
* **Server mode:** set `TIMEOS_API_TOKEN`; every `/api` route except `/api/health` then
  requires `Authorization: Bearer <token>` (constant-time comparison). The UI stores the token
  locally after the user enters it on the Settings page. A full session-cookie login can replace
  this later without touching services.
* **Secrets** come only from environment variables (`.env`, never committed). The browser
  never receives the Anthropic key or Google client secret; all third-party calls are made by
  the backend.
* **Google OAuth (Phase 3):** authorization-code flow with PKCE and `state` validation,
  run by the backend. Refresh tokens are encrypted at rest with Fernet using
  `TIMEOS_SECRET_KEY`. Scopes: `calendar.readonly` by default; `calendar.events` only after the
  user enables a calendar mode that writes.
* **Input validation:** Pydantic models with length and range limits on every endpoint;
  upload size limit for imports; CORS restricted to configured origins.
* **Audit log:** every destructive or automatic action (deletes, imports and their rollback,
  AI-initiated changes, scheduler moves) is written to `audit_log` with before/after state.
* **Data minimisation for Claude:** the context builder sends only the records a question
  needs (see [claude-tools.md](claude-tools.md)).

## 8. Provenance and user control

Every task, session and (later) schedule block records where it came from, so the UI can
always show whether something is *user-created, AI-suggested, automatically scheduled,
imported* or *a Google Calendar event*:

* `tasks.source`: `user | ai | import | recurrence`, plus `pending_approval` for AI-proposed
  tasks that the user has not accepted yet. Pending tasks are excluded from planning.
* `focus_sessions.source`: `timer | manual | import`.
* `schedule_blocks.origin` and `calendar_events.origin` (Phases 3–4).

Automatic behaviour is opt-in through settings: `scheduling_mode`
(`manual | suggest | auto`), `calendar_mode` (`read_only | suggest | auto_create`) and
`require_approval_for_ai_tasks`.
