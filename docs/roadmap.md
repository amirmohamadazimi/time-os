# Development roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | Project setup, database + migrations, task CRUD (dependencies, recurrence, inbox, provenance), projects, focus timer, dashboard, audit log, settings, React UI, Docker Compose, CI | ✅ in this repository |
| 2 Historical data | Focus-session CSV importer (dry run, dedupe, quality flags, rollback), session history, productivity analytics, estimation accuracy, observed patterns | ✅ in this repository |
| 3 Google Calendar | Read-only sync from the secret iCal address, encrypted link, free/busy, calendar view; then OAuth, incremental sync and writing focus blocks | iCal ✅; OAuth designed ([google-calendar.md](google-calendar.md)) |
| 4 Scheduler | Availability, scoring, placement, capacity report, validation, rescheduling, explanations | interface defined ([scheduler.md](scheduler.md)) |
| 5 Claude | Provider adapter, chat with tool use, context builder, task decomposition, daily/weekly reviews | tool registry live ([claude-tools.md](claude-tools.md)) |
| 6 Personalization | Multipliers in scheduling, productive-hour placement, postponement/abandonment analysis | multipliers computed in Phase 2 |
| 7 Advanced | Automatic rescheduling, long-term trends, project forecasting ("where does a 10h project fit?") | |

Next up: the Phase 4 scheduler, which reads busy time from the calendar cache. OAuth (Phase 3b)
is needed only for writing focus blocks to Google Calendar and requires a Google Cloud OAuth client
that the user creates.
