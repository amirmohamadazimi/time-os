# Progress

Living status file so work can resume cleanly in a new session.
Spec: the project thread's root message (sections 2–46). Plan: [docs/roadmap.md](docs/roadmap.md).
Merged: Phases 1–2 (PR #1), importer fix for the real FocusMeter export (PR #2), single-process
image and free hosting on Render + Neon (PR #3), read-only Google Calendar via iCal link (PR #4).

## Done: Phases 1 and 2
- **Contracts** in `docs/`: architecture, database schema, API, scheduler interface, Claude tools,
  Google Calendar design, focus sessions, CSV import, analytics, testing, roadmap.
- **Backend** (`backend/`, FastAPI + SQLAlchemy + Alembic, SQLite or PostgreSQL): projects, tasks
  (dependencies with cycle check, RRULE recurrence, inbox, AI approval, provenance), server-side focus
  timer, session history, settings, audit log, Today dashboard, CSV importer (preview, dedupe, quality
  flags, rollback), analytics (summary, timeseries, by hour/weekday/project/tag, gaps, observed patterns,
  estimation multipliers), scheduler interface types (`app/scheduler/types.py`), Claude tool registry
  (`app/ai/tools.py`, 13 tools).
- **Tests**: 127 backend tests pass on SQLite and PostgreSQL 16 (including migrations); 10 frontend tests.
- **Frontend** (`frontend/`, React 19 + Vite + Mantine 8 + TanStack Query): Dashboard, Tasks, Projects,
  Focus, Sessions, Analytics, Import, Settings. Smoke-tested against a live API in headless Chromium.
- **Ops**: one root `Dockerfile` (UI built with Node, served by the API; uv, non-root, healthcheck,
  honours `$PORT`), `docker-compose.yml` (SQLite) and `docker-compose.postgres.yml`; `render.yaml` for
  free hosting on Render with Neon Postgres ([docs/deploy.md](docs/deploy.md)); `.env.example`;
  GitHub Actions CI (ruff, pytest on SQLite + PostgreSQL, frontend checks, image builds).

## Next
1. **Phase 3, Google Calendar**: read-only sync from the secret iCal address is done (PR #4): encrypted link, recurrence expansion, tombstones, free time, Calendar page and Today
   card. OAuth (writing focus blocks) stays designed in `docs/google-calendar.md` and needs a Google Cloud
   OAuth client the user creates; the user chose iCal first (2026-10-01).
2. **Phase 4, Scheduler**: implement `app/scheduler/` against `types.py` and `docs/scheduler.md`
   (availability → scoring → placement → validation → capacity report → rescheduling). Pure functions, heavy tests.
3. **Phase 5, Claude**: provider adapter (Anthropic SDK, `TIMEOS_AI_MODEL`, default `claude-opus-5-5`),
   chat endpoint with tool use over `app/ai/tools.py`, minimal-context builder, reviews. Mocked in tests.
4. ~~Validate the importer on the user's real export~~ done in PR #2 (synthetic fixture with the same shape).

## Open questions for the user
- Google Cloud OAuth client, only if Time OS should write focus blocks to Google Calendar.

## Dev quickstart
```
cd backend && uv sync --extra postgres && uv run --extra postgres uvicorn app.main:create_app --factory --reload
cd frontend && npm install && npm run dev        # http://localhost:5173
cd frontend && npm run build                      # then the API alone serves UI + API on http://localhost:8000
docker compose up -d --build                      # or the one-container stack on http://localhost:8080
```
Note: `uv run` re-syncs the environment, so pass `--extra postgres` whenever psycopg is needed.
