# Focus-session CSV import

Imports a focus app's export into the session database so historical behaviour feeds analytics and
estimate learning. Code: `backend/app/importer/` (`parsing.py` and `focus_csv.py` are pure;
`service.py` does the database work). API: [api.md](api.md#imports).

## Workflow

1. **Preview** (`dry_run=true`, the default): parse, validate and de-duplicate, then return a summary
   and the problem rows. Nothing is written.
2. **Commit** (`dry_run=false`): the same pipeline, then writes an `import_batches` row, one
   `import_records` row per CSV row (raw data preserved, status `imported`/`duplicate`/`invalid`),
   and the new `focus_sessions`. Audited as `import.committed`.
3. **Rollback** (`DELETE /api/imports/{id}`): voids every session the batch created and frees their
   external ids so the file can be imported again. Raw records stay for reference. Audited.

## Columns

Header matching ignores case, spaces, underscores and punctuation. Only a start time plus either an
end time or a duration is required.

| Field | Accepted headers |
|---|---|
| id | `id`, `sessionId`, `uuid` |
| start | `startTime`, `start`, `startedAt`, `startDate`, `begin` |
| end | `endTime`, `end`, `endedAt`, `endDate`, `finishTime`, `stopTime` |
| duration | `duration`, `durations`, `length`, `activeDuration`, `focusDuration`, `focusTime` |
| paused | `totalPausedTime`, `pausedTime`, `paused`, `pauseTime`, `pausedDuration` |
| completed / stopped | `completed`, `isCompleted` / `stopped`, `isStopped`, `interrupted` |
| type | `type`, `sessionType`, `kind`, `mode` |
| notes / tags | `notes`, `note`, `comment`, `description` / `tags`, `tag`, `labels` |

Encodings: UTF-8 (with or without BOM), UTF-16, then Latin-1. Delimiter is sniffed (`,` `;` tab `|`).

### Multi-section exports (FocusMeter)

Some apps write several tables into one file, each introduced by a `Name: <section>` line
(FocusMeter: `sessions`, `events`, `tags`, `session-tags`, `timeblocks`, `flows`, then settings and
export metadata). The importer splits the file, imports the `sessions` section, and uses
`timeblocks` when present: each block is one uninterrupted run of the timer, so their sum is the
exact active time and their count minus one is the number of pauses. This matters when a timer
finished and sat waiting for the user, time that `end − start − paused` would count as focus
(`active_from_timeblocks` warning). Other sections are ignored.

## Value parsing

- **Timestamps**: ISO 8601 with `Z` or an offset; naive date-times (interpreted in the timezone
  chosen at import, flagged `assumed_timezone`); common formats via dateutil; Unix epoch in seconds or
  milliseconds. Years outside 1990–2100 are rejected.
- **Durations**: `01:25:00`, `25:00`, `PT25M`, `1h 30m`, `90 min` carry their own unit. A bare number's
  unit is chosen **once per file**: rows that have both timestamps vote for the unit that best
  reproduces their elapsed time; otherwise the median magnitude decides. The choice is shown in the
  preview and can be overridden (`duration_unit`).
- **Type**: work (`work`, `focus`, `pomodoro`, …) or rest (`break`, `short break`, `rest`, …). Missing
  means work (warning); an unknown value makes the row invalid.
- **Tags**: comma, semicolon or pipe separated, a JSON list, or `#hash #tags`. De-duplicated
  case-insensitively.
- **Booleans**: true/false, yes/no, 1/0, t/f. `completed` → `end_reason=completed`, `stopped` →
  `stopped`, neither → `unknown`.

## Derivation and validation

- **Duration column meaning** is decided once per file. Pomodoro-style apps export the *planned* timer
  length: completed sessions match it and stopped sessions fall short of it. When at least 90 % of
  completed rows match their measured active time and at least 80 % of stopped rows fall short, the
  column is read as the plan and stored as `planned_duration_s`; otherwise it is time worked. The
  preview shows which (`duration_meaning`).
- An end time of `1970-01-01…` (or `0`) means the session was still running at export: the row is
  invalid with `unfinished_session` and can be imported from a later export.
- Missing end → `start + duration + paused` (`end_time_derived`). Missing start → `end − duration − paused`.
- Missing paused time with a duration clearly shorter than elapsed → paused inferred (`paused_inferred`).
- **Timestamps win** over a reported duration that disagrees by more than max(60 s, 5 %)
  (`duration_mismatch` warning).
- Invalid rows: unparseable timestamps, end before start, paused longer than the session, unknown
  type, wrong field count (`malformed_row`), no start, or neither end nor duration.

## Quality flags

Flags keep suspicious sessions visible without silently distorting statistics. Thresholds are in
Settings → Import quality rules.

| Flag | Default rule | Excluded from analytics |
|---|---|---|
| `too_short` | active < 60 s (accidental taps) | yes |
| `zero_length` | start = end | yes |
| `long_active` | active > 240 min | only together with `implausible_elapsed` |
| `long_pause` | paused > 120 min | no |
| `implausible_elapsed` | elapsed > 16 h | only together with `long_active` (a timer left running). A long elapsed time explained by pauses keeps its focus time. |

Exclusion can be toggled per session on the Sessions page.

## Duplicates

A row is a duplicate when:

- its `id` was already imported (a session you deleted individually still counts; rolling back a whole
  batch frees its ids), or
- another row in the same file, or an existing session of any source, has the same type, a start
  within the tolerance (default 60 s), the same active duration within the tolerance, **and overlaps
  it in time**. Two real sessions cannot overlap, so accidental taps a few seconds apart stay separate.

Re-importing the same file is therefore safe: every row comes back as a duplicate. The preview also
says when the exact file (by SHA-256) was imported before.

## Limits

Uploads are capped by `TIMEOS_MAX_UPLOAD_MB` (default 20). The preview lists at most 500 problem rows;
all rows are kept in `import_records` after a commit.
