# Running Time OS: on your computer or free in the cloud

Time OS is one small process: the API also serves the web UI. It needs about 140 MB of RAM
(104 MB measured inside the container). When Docker feels heavy, the cost is Docker Desktop's
virtual machine, not the app, so there are two lighter options.

| Option | Cost | RAM on your computer | Notes |
|---|---|---|---|
| [On your computer, no Docker](#on-your-computer-without-docker) | free | ~140 MB while it runs | Data stays on your machine (SQLite file). |
| [Render + Neon](#free-in-the-cloud-render--neon) | $0, no card | none | Reachable from any device. Sleeps after 15 minutes idle; the first visit after that takes about a minute. |
| Docker Compose | free | app + Docker Desktop | Same image as Render. See the README. |

GitHub itself cannot host it: GitHub Pages serves static files only, and Time OS needs a server
and a database. Codespaces can run it but stops when idle and has a monthly hour limit, so it is
not a host.

## On your computer, without Docker

Install once: [Python 3.11+](https://www.python.org/downloads/), [uv](https://docs.astral.sh/uv/getting-started/installation/)
and [Node 22](https://nodejs.org/). Then, from the repository folder:

```bash
cd frontend
npm ci
npm run build          # once, and again after pulling UI changes
cd ../backend
uv sync
uv run uvicorn app.main:create_app --factory --port 8000
```

Open http://localhost:8000. Your data is in `backend/data/timeos.db`; copy that file to back it up
(stop the server first). Stop the server with Ctrl+C. Migrations run on every start, so pulling new
code and restarting is the whole upgrade.

Set your timezone in Settings, or start with `TIMEOS_DEFAULT_TIMEZONE=Asia/Tehran` (or any other
zone) in `backend/.env` so first-run settings use it.

## Free in the cloud: Render + Neon

[Render](https://render.com) runs the container for free. Its free services have no persistent
disk and its free Postgres is deleted after 30 days, so the data lives in a free
[Neon](https://neon.tech) Postgres database instead, which does not expire. Neither needs a card.

The app is then on the public internet, so every API call needs the access token
(`TIMEOS_API_TOKEN`). Render generates a long random one for you; the UI asks for it once per browser.
Traffic is HTTPS.

### 1. Create the database (Neon)

1. Sign up at https://neon.tech (GitHub sign-in works) and create a project. Pick the region closest
   to you, ideally the same one you will pick on Render (for example AWS Frankfurt).
2. On the project dashboard, click **Connect**, turn **Connection pooling** off, and copy the
   connection string. It looks like
   `postgresql://neondb_owner:…@ep-….eu-central-1.aws.neon.tech/neondb?sslmode=require`.
   Keep it private: it is the password to your data.

### 2. Deploy the app (Render)

1. Sign up at https://render.com with your GitHub account and allow it to read the `time-os`
   repository.
2. Click **New → Blueprint**, pick the repository and branch `main`. Render reads
   [`render.yaml`](../render.yaml): one free web service in Frankfurt, built from the `Dockerfile`.
3. When it asks for `TIMEOS_DATABASE_URL`, paste the Neon connection string. Click **Apply**.
   The first build takes a few minutes; tables are created on first start.
4. Open the service, go to **Environment**, and reveal `TIMEOS_API_TOKEN`. Copy it into a password
   manager.
5. Open the service URL (`https://timeos-….onrender.com`) and paste the token when asked.

To change the timezone used for first-run settings, edit `TIMEOS_DEFAULT_TIMEZONE` in the same
**Environment** page (it is set to `Asia/Tehran`); after first run, change it in the app's Settings.

### What to expect

- **Sleeping.** After 15 minutes without visits Render stops the service; the next visit wakes it in
  about a minute. A running focus timer is not lost: its start time and pauses are stored in the
  database, so elapsed time is correct when the server wakes.
- **Do not add an uptime pinger** to keep it awake. The health check touches the database, so
  pinging it around the clock keeps Neon awake too and uses up Neon's free monthly compute hours.
- **Updates.** Every push to `main` redeploys automatically (`autoDeploy` in `render.yaml`).
- **Backups.** `pg_dump "<neon connection string>" > timeos-backup.sql` from any machine with
  PostgreSQL client tools, or use Neon's branch and restore features.
- **Changing the token.** Edit `TIMEOS_API_TOKEN` in Render's **Environment** page; each browser
  will ask for the new one.
- **Moving back to your computer.** Run locally with `uv sync --extra postgres`, then
  `TIMEOS_DATABASE_URL=<neon connection string> uv run --extra postgres uvicorn app.main:create_app --factory`
  to use the same data, or dump and restore into a local database.

If Render or Neon will not let you sign up from your country, use the
[no-Docker local setup](#on-your-computer-without-docker): it is the same app.

## Configuration reference

All settings are environment variables; see the table in the [README](../README.md#configuration).
Hosted providers hand out `postgres://…` URLs; Time OS rewrites them to the psycopg driver, so they
can be pasted as they are.
