# Progress

Living status file so work can resume cleanly in a new session.
Spec: the project thread's root message (sections 2–46). Plan: [docs/roadmap.md](docs/roadmap.md).
Phases 1–2 merged via PR #1. Importer fix for the real FocusMeter export: PR #2. Single-process
image and free hosting (Render + Neon): branch `single-service-deploy`.

## Done: Phases 1 and 2
- **Contracts** in `docs/`: architecture, database schema, API, scheduler interface, Claude tools,
  Google Calendar design, focus sessions, CSV import, analytics, testing, roadmap.
- **Backend** (`backend/`, FastAPI + SQLAlchemy + Alembic, SQLite or PostgreSQL): projects, tasks
  (dependencies with cycle check, RRULE recurrence, inbox, AI approval, provenance), server-side focus
  timer, session history, settings, audit log, Today dashboard, CSV importer (preview, dedupe, quality
  flags, rollback), analytics (summary, timeseries, by hour/weekday/project/tag, gaps, observed patterns,
  estimation multipliers), scheduler interface types (`app/scheduler/types.py`), Claude tool registry
  (`app/ai/tools.py`, 13 tools).
- **Tests**: 102 backend tests pass on SQLite and PostgreSQL 16 (including migrations); 10 frontend tests.
- **Frontend** (`frontend/`, React 19 + Vite + Mantine 8 + TanStack Query): Dashboard, Tasks, Projects,
  Focus, Sessions, Analytics, Import, Settings. Smoke-tested against a live API in headless Chromium.
- **Ops**: one root `Dockerfile` (UI built with Node, served by the API; uv, non-root, healthcheck,
  honours `$PORT`), `docker-compose.yml` (SQLite) and `docker-compose.postgres.yml`; `render.yaml` for
  free hosting on Render with Neon Postgres ([docs/deploy.md](docs/deploy.md)); `.env.example`;
  GitHub Actions CI (ruff, pytest on SQLite + PostgreSQL, frontend checks, image builds).

## Next
1. **Phase 3, Google Calendar** (design in `docs/google-calendar.md`): full OAuth needs a Google Cloud
   OAuth client the user creates (Claude cannot create it on their account). Read-only alternative with
   no Google Cloud project: the calendar's "secret address in iCal format". Encrypted token storage (`TIMEOS_SECRET_KEY`), incremental sync,
   free/busy, event classification (never modify `USER_CREATED_EVENT`), calendar view. Tests with a fake client.
2. **Phase 4, Scheduler**: implement `app/scheduler/` against `types.py` and `docs/scheduler.md`
   (availability → scoring → placement → validation → capacity report → rescheduling). Pure functions, heavy tests.
3. **Phase 5, Claude**: provider adapter (Anthropic SDK, `TIMEOS_AI_MODEL`, default `claude-opus-5-5`),
   chat endpoint with tool use over `app/ai/tools.py`, minimal-context builder, reviews. Mocked in tests.
4. ~~Validate the importer on the user's real export~~ done in PR #2 (synthetic fixture with the same shape).

## Open questions for the user
- Google Calendar: OAuth client, or the read-only secret iCal address.

## Dev quickstart
```
cd backend && uv sync --extra postgres && uv run --extra postgres uvicorn app.main:create_app --factory --reload
cd frontend && npm install && npm run dev        # http://localhost:5173
cd frontend && npm run build                      # then the API alone serves UI + API on http://localhost:8000
docker compose up -d --build                      # or the one-container stack on http://localhost:8080
```
Note: `uv run` re-syncs the environment, so pass `--extra postgres` whenever psycopg is needed.
