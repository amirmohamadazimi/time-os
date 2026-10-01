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
| `long_active` | active > 240 min | no |
| `long_pause` | paused > 120 min | no |
| `implausible_elapsed` | elapsed > 16 h (for example, a timer left running overnight) | yes |
| `zero_length` | start = end | yes |

Exclusion can be toggled per session on the Sessions page.

## Duplicates

A row is a duplicate when:

- its `id` was already imported (a session you deleted individually still counts; rolling back a whole
  batch frees its ids), or
- another row in the same file, or an existing session of any source, has the same type, a start
  within the tolerance (default 60 s) and the same active duration within the tolerance.

Re-importing the same file is therefore safe: every row comes back as a duplicate. The preview also
says when the exact file (by SHA-256) was imported before.

## Limits

Uploads are capped by `TIMEOS_MAX_UPLOAD_MB` (default 20). The preview lists at most 500 problem rows;
all rows are kept in `import_records` after a commit.
