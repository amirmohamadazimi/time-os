# Progress

Living status file so work can resume cleanly in a new session.
Spec: the project thread's root message (sections 2–46). Plan: [docs/roadmap.md](docs/roadmap.md).
Branch `foundation-phase-1-2`, draft PR #1.

## Done: Phases 1 and 2
- **Contracts** in `docs/`: architecture, database schema, API, scheduler interface, Claude tools,
  Google Calendar design, focus sessions, CSV import, analytics, testing, roadmap.
- **Backend** (`backend/`, FastAPI + SQLAlchemy + Alembic, SQLite or PostgreSQL): projects, tasks
  (dependencies with cycle check, RRULE recurrence, inbox, AI approval, provenance), server-side focus
  timer, session history, settings, audit log, Today dashboard, CSV importer (preview, dedupe, quality
  flags, rollback), analytics (summary, timeseries, by hour/weekday/project/tag, gaps, observed patterns,
  estimation multipliers), scheduler interface types (`app/scheduler/types.py`), Claude tool registry
  (`app/ai/tools.py`, 13 tools).
- **Tests**: 123 backend tests pass on SQLite and PostgreSQL 16 (including migrations); 10 frontend tests.
- **Frontend** (`frontend/`, React 19 + Vite + Mantine 8 + TanStack Query): Dashboard, Tasks, Projects,
  Focus, Sessions, Analytics, Import, Settings. Smoke-tested against a live API in headless Chromium.
- **Ops**: Dockerfiles (backend: uv, non-root, healthcheck; frontend: nginx proxying `/api`),
  `docker-compose.yml` (SQLite) and `docker-compose.postgres.yml`, both run end to end; `.env.example`;
  GitHub Actions CI (ruff, pytest on SQLite + PostgreSQL, frontend checks, image builds).

## Next
1. **Phase 3, Google Calendar**: read-only sync from the secret iCal address is done (branch
   `calendar-ical`): encrypted link, recurrence expansion, tombstones, free time, Calendar page and Today
   card. OAuth (writing focus blocks) stays designed in `docs/google-calendar.md` and needs a Google Cloud
   OAuth client the user creates; the user chose iCal first (2026-10-01).
2. **Phase 4, Scheduler**: implement `app/scheduler/` against `types.py` and `docs/scheduler.md`
   (availability → scoring → placement → validation → capacity report → rescheduling). Pure functions, heavy tests.
3. **Phase 5, Claude**: provider adapter (Anthropic SDK, `TIMEOS_AI_MODEL`, default `claude-opus-5-5`),
   chat endpoint with tool use over `app/ai/tools.py`, minimal-context builder, reviews. Mocked in tests.
4. Validate the importer on the user's real export and add it (anonymised) as a fixture.

## Open questions for the user
- A real focus-session export sample (to confirm units, timestamps and tags).
- Google Cloud OAuth client, only if Time OS should write focus blocks to Google Calendar.

## Dev quickstart
```
cd backend && uv sync --extra postgres && uv run --extra postgres uvicorn app.main:create_app --factory --reload
cd frontend && npm install && npm run dev        # http://localhost:5173
docker compose up -d --build                      # or the full stack on http://localhost:8080
```
Note: `uv run` re-syncs the environment, so pass `--extra postgres` whenever psycopg is needed.
