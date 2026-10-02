# Time OS

A personal time-management operating system: a deterministic productivity engine for tasks,
focus sessions, history and analytics, with Claude planned as the reasoning and conversational layer
on top. Claude is never the source of truth: it acts only through the same validated actions as the UI.

It keeps three things apart:

- **Plan**: tasks and projects (estimates, deadlines, dependencies, recurrence, priorities)
- **Available time**: your calendar (Google Calendar via its secret iCal address)
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
- Google Calendar (or any iCal feed) via its secret address: read-only sync, recurring events,
  busy/free time inside working hours, a week view and a Today card. No Google Cloud setup.
- A Today dashboard, settings, an audit log for destructive and AI actions, and a Claude tool registry
  (tested with mocks; the chat layer comes in Phase 5).

## Run it

Time OS is one process: the API also serves the UI, using about 140 MB of RAM.
[docs/deploy.md](docs/deploy.md) has all three options in detail.

**On your computer, without Docker** (lightest; needs Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node 22):

```bash
cd frontend && npm ci && npm run build && cd ..
cd backend && uv sync && uv run uvicorn app.main:create_app --factory --port 8000
```

Open http://localhost:8000. Data is in `backend/data/timeos.db`.

**Free in the cloud** on Render with a Neon Postgres database: no card, reachable from any device,
protected by an access token. It sleeps after 15 idle minutes and takes about a minute to wake.
Steps in [docs/deploy.md](docs/deploy.md#free-in-the-cloud-render--neon).

**Docker Compose** (one container, SQLite in the `timeos-data` volume):

```bash
cp .env.example .env        # optional: set TIMEOS_API_TOKEN and TIMEOS_DEFAULT_TIMEZONE
docker compose up -d --build
```

Open http://localhost:8080 (bound to 127.0.0.1 only). PostgreSQL instead of SQLite (set
`POSTGRES_PASSWORD` in `.env` first):

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d --build
```

To back up SQLite, stop the app so the write-ahead log is flushed, then copy the file:

```bash
docker compose stop app && docker compose cp app:/app/data/timeos.db ./timeos-backup.db && docker compose start app
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
| `TIMEOS_DATABASE_URL` | `sqlite:///./data/timeos.db` | SQLAlchemy URL; PostgreSQL as `postgresql+psycopg://…` (hosted `postgres://…` URLs work as they are) |
| `TIMEOS_API_TOKEN` | unset | When set, every API call needs `Authorization: Bearer <token>` |
| `TIMEOS_DEFAULT_TIMEZONE` | `UTC` | Timezone for first-run settings |
| `TIMEOS_AUTO_MIGRATE` | `true` | Run Alembic migrations on startup |
| `TIMEOS_CORS_ORIGINS` | Vite dev server | Allowed browser origins (JSON list) |
| `TIMEOS_MAX_UPLOAD_MB` | `20` | CSV upload limit |
| `TIMEOS_STATIC_DIR` | `../frontend/dist` | Built UI to serve; the UI is skipped when the folder has no `index.html` |
| `TIMEOS_SECRET_KEY` | unset | Encrypts stored secrets (calendar links). Unset: a random key is created in `TIMEOS_SECRET_KEY_FILE` |
| `TIMEOS_SECRET_KEY_FILE` | `./data/secret.key` | Where that generated key lives; back it up with the database |

## Privacy and security

- Your data is in your own database: on your machine, or in your own Neon database when you host it
  yourself. Nothing is sent anywhere else today.
- Times are stored in UTC with the local offset recorded per session.
- Optional bearer token, compared in constant time. Without it, anyone who can reach the port can use the API;
  the Render setup always generates one. The UI asks for it once per browser.
- Destructive and AI-initiated actions are written to the audit log.
- API keys for Google and Anthropic (later phases) stay server-side and are never sent to the browser.

## Documentation

[Running and free hosting](docs/deploy.md) · [Architecture](docs/architecture.md) · [Database schema](docs/database-schema.md) · [API](docs/api.md) ·
[Focus sessions](docs/focus-sessions.md) · [CSV import](docs/csv-import.md) · [Analytics](docs/analytics.md) ·
[Scheduler interface](docs/scheduler.md) · [Claude tools](docs/claude-tools.md) ·
[Google Calendar design](docs/google-calendar.md) · [Testing](docs/testing.md) · [Roadmap](docs/roadmap.md)

Current status and next steps: [PROGRESS.md](PROGRESS.md).
