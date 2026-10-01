# Progress

Living status file so work can resume cleanly in a new session.
Spec: the project thread's root message (sections 2–46). Plan: [docs/roadmap.md](docs/roadmap.md).

## Done
- Contracts: [architecture](docs/architecture.md), [database schema](docs/database-schema.md),
  [API](docs/api.md), [scheduler interface](docs/scheduler.md), [Claude tools](docs/claude-tools.md),
  [Google Calendar design](docs/google-calendar.md), [roadmap](docs/roadmap.md).
- Backend skeleton (`backend/`): config, DB (`UTCDateTime`), ORM models for all Phase 1–2 tables,
  Alembic initial migration (`0001`), Pydantic schemas.
- Services: projects, tasks (dependencies + cycle check, inbox capture, approval, provenance),
  recurrence (RRULE templates → occurrences), focus timer state machine, session history
  (manual log, annotate, void), settings, audit log.
- API routers: health, projects, tasks, focus, sessions, settings, audit. Smoke-tested by hand.

## Next (in order)
1. `backend/tests/` for Phase 1 (tasks, dependencies, recurrence, focus timer durations, sessions, migrations).
2. Dashboard service + `/api/dashboard/today`.
3. Phase 2: CSV importer (`app/importer/`: pure parser + service), import API, synthetic messy fixture,
   analytics engine (`app/analytics/`) + `/api/analytics/*`, estimation multipliers, observed patterns.
4. `app/scheduler/types.py` (interface dataclasses from docs/scheduler.md) and `app/ai/tools.py` registry + tests.
5. Frontend (`frontend/`): Vite + React + TS + Mantine + TanStack Query; pages Dashboard, Tasks, Projects,
   Focus, Sessions, Import, Analytics, Settings.
6. Docker (backend + frontend/nginx), `docker-compose.yml`, `docker-compose.postgres.yml`, `.env.example`,
   GitHub Actions CI (ruff, pytest on SQLite + PostgreSQL, frontend build).
7. Docs still to write: focus-sessions.md, analytics.md, csv-import.md, testing.md; README quickstart.

## Open questions for the user
- Real focus-session export sample (to validate importer units/timestamps/tags).

## Dev quickstart (backend)
```
cd backend
uv sync --extra postgres
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --reload
```
