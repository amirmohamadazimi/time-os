# Testing

## Running the tests

```bash
# Backend: 104 tests, SQLite in memory by default
cd backend
uv sync --extra postgres
uv run ruff check . && uv run ruff format --check .
uv run pytest

# The same suite against PostgreSQL
TIMEOS_TEST_DATABASE_URL=postgresql+psycopg://timeos:timeos@localhost:5432/timeos_test \
  uv run --extra postgres pytest

# Frontend
cd frontend
npm ci
npm run typecheck && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above on every pull request: the backend suite on
SQLite and on PostgreSQL 16, the frontend checks, and a build of both Docker images.

## How the backend tests are built

- **Real database, no mocks of our own code.** Each test gets a fresh schema (`tests/conftest.py`).
  On SQLite it is in memory; with `TIMEOS_TEST_DATABASE_URL` the tables are created in that database
  and dropped afterwards.
- **Fake clock.** Services take `now` as an argument and the API reads it from the `get_now`
  dependency, which the tests override with `FakeClock`. Timer tests advance time explicitly
  (`clock.advance(minutes=25)`), so durations are exact and nothing sleeps.
- **Through the HTTP API** for behaviour users depend on (status codes, validation errors, response
  shapes), and **directly against pure functions** for parsers and metrics.
- **Migrations**: `test_migrations.py` runs `alembic upgrade head` on an empty database (a SQLite file, or
  the PostgreSQL test database), checks the result matches the ORM models exactly, then downgrades.
- **No live external calls.** Claude is exercised through the tool registry with a mocked context;
  Google Calendar is not implemented yet and will be tested against a fake client.

## Coverage map

| Area | File | Covers |
|---|---|---|
| Projects | `test_projects_api.py` | CRUD, unique names, archive, delete blocked when in use, stats |
| Tasks | `test_tasks_api.py` | CRUD, validation, inbox capture, approval of AI proposals, completion, filters, audit |
| Dependencies | `test_dependencies.py` | strict vs soft, cycle detection, blocked_by, cancelled prerequisites |
| Recurrence | `test_recurrence.py` | RRULE validation, occurrence generation, idempotency, template deletion |
| Focus timer | `test_focus_timer.py` | start/pause/resume/finish durations, single live session, switch, discard, outcomes, task state |
| Sessions | `test_sessions.py` | manual log (overlap, future), immutable history, annotations, soft delete |
| Settings and auth | `test_settings_and_auth.py` | deep-merge updates, validation, bearer token |
| Import parsing | `test_import_parsing.py` | timestamps (ISO, offsets, naive, epoch), durations, booleans, types, tags |
| Import service | `test_import_service.py` | both fixtures below, dry run vs commit, re-import, rollback, bad files, settings |
| Analytics | `test_analytics.py` | summary metrics, hour spreading, weekday averages, tags, estimation shrinkage, patterns |
| Dashboard | `test_dashboard.py` | today totals including the live session, next-task ordering, due and overdue |
| Claude tools | `test_ai_tools.py` | tool schemas, validation errors, confirmation gating, approval flow |

## The messy import fixture

`backend/tests/fixtures/focus_messy.csv` has 15 rows built to cover the spec's importer cases:
valid rows with offsets and `Z`, a naive timestamp, epoch seconds, millisecond precision, a missing
end (derived), a missing type, a missing duration and paused time, a long pause, a timer left running
overnight, an exact duplicate id, a same-session duplicate with a different id, an unparseable start, an
end before start, an unknown type, and a row with an extra field. Expected result: 9 imported,
2 duplicates, 4 invalid.

`backend/tests/fixtures/focusmeter_export.csv` is a synthetic file in FocusMeter's multi-section format,
modelled on a real export (the real data is not committed). It covers planned-duration detection,
timer blocks that correct an idle finished timer, accidental taps seconds apart, an overnight pause,
and a session still running at export.

## Frontend

Vitest covers the pure logic the UI depends on (`src/lib/*.test.ts`: formatting and the live timer
maths, including clock-skew correction). Pages were smoke-tested against a running API in headless
Chromium; component tests can be added as the UI settles.
