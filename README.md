# Time OS

A personal time-management operating system: a deterministic productivity engine for tasks,
focus sessions, history and analytics, with Claude planned as the reasoning and conversational layer
on top. Claude is never the source of truth: it acts only through the same validated actions as the UI.

It keeps three things apart:

- **Plan**: tasks and projects (estimates, deadlines, dependencies, recurrence, priorities)
- **Available time**: your calendar (Google Calendar, Phase 3)
- **Actual behaviour**: focus sessions, from the built-in timer or imported history

## What works today (Phases 1 and 2)

- Tasks with projects, categories, tags, priority, importance/urgency, estimates, deadlines, planned
  dates, strict or soft dependencies (cycle-checked), RRULE recurrence, an inbox for quick capture,
  and provenance (user, AI, import, recurrence). AI-created tasks wait for your approval.
- A server-side focus timer: start, pause, resume, switch task, finish with an outcome. It survives
  refreshes and works across devices.
- Session history: manual logging, notes and tags, exclude-from-stats, soft delete. Times are immutable.
- CSV import of focus-app exports with preview, duplicate detection, quality flags and one-click rollback.
- Analytics: focus over time, by hour and weekday, by project and tag, completion and interruption
  rates, observed patterns, and estimate accuracy with shrunk planning multipliers.
- A Today dashboard, settings, an audit log for destructive and AI actions, and a Claude tool registry
  (tested with mocks; the chat layer comes in Phase 5).

## Quick start (Docker)

```bash
cp .env.example .env        # optional: set TIMEOS_API_TOKEN and TIMEOS_DEFAULT_TIMEZONE
docker compose up -d --build
```

Open http://localhost:8080. Data lives in the `timeos-data` volume (SQLite). The UI is bound to
127.0.0.1 and the API is reachable only through it.

PostgreSQL instead of SQLite (set `POSTGRES_PASSWORD` in `.env` first):

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --build
```

To back up SQLite, stop the API so the write-ahead log is flushed, then copy the file:

```bash
docker compose stop api && docker compose cp api:/app/data/timeos.db ./timeos-backup.db && docker compose start api
```

## Development

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
# API on http://localhost:8000 (docs at /api/docs); migrations run on startup
cd backend
uv sync --extra postgres
uv run --extra postgres uvicorn app.main:create_app --factory --reload

# UI on http://localhost:5173, proxying /api to the backend
cd frontend
npm install
npm run dev
```

Tests and CI are described in [docs/testing.md](docs/testing.md).

## Configuration

Deployment settings are environment variables (or `.env`). Personal preferences such as timezone,
working hours, timer lengths and automation modes are edited in the app's Settings page.

| Variable | Default | Purpose |
|---|---|---|
| `TIMEOS_DATABASE_URL` | `sqlite:///./data/timeos.db` | SQLAlchemy URL; `postgresql+psycopg://…` for PostgreSQL |
| `TIMEOS_API_TOKEN` | unset | When set, every API call needs `Authorization: Bearer <token>` |
| `TIMEOS_DEFAULT_TIMEZONE` | `UTC` | Timezone for first-run settings |
| `TIMEOS_AUTO_MIGRATE` | `true` | Run Alembic migrations on startup |
| `TIMEOS_CORS_ORIGINS` | Vite dev server | Allowed browser origins (JSON list) |
| `TIMEOS_MAX_UPLOAD_MB` | `20` | CSV upload limit |

## Privacy and security

- Local-first: everything is stored in your own database; nothing leaves the machine today.
- Times are stored in UTC with the local offset recorded per session.
- Optional bearer token, compared in constant time. Without it, anyone who can reach the port can use the API.
- Destructive and AI-initiated actions are written to the audit log.
- API keys for Google and Anthropic (later phases) stay server-side and are never sent to the browser.

## Documentation

[Architecture](docs/architecture.md) · [Database schema](docs/database-schema.md) · [API](docs/api.md) ·
[Focus sessions](docs/focus-sessions.md) · [CSV import](docs/csv-import.md) · [Analytics](docs/analytics.md) ·
[Scheduler interface](docs/scheduler.md) · [Claude tools](docs/claude-tools.md) ·
[Google Calendar design](docs/google-calendar.md) · [Testing](docs/testing.md) · [Roadmap](docs/roadmap.md)

Current status and next steps: [PROGRESS.md](PROGRESS.md).
