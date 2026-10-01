# Analytics

Deterministic statistics over finished focus sessions. Everything here is **observed**: computed
from data, labelled `kind: "observed"`, with sample sizes. Explanations ("why") are left to the AI
layer, which must label them separately. Code: `backend/app/analytics/`; API: [api.md](api.md#analytics-observed-statistics).

## What is counted

- Finished, not deleted, not `exclude_from_stats` sessions. The number excluded is reported in `meta`.
- Work sessions by default (`type=work`); rest is reported separately where relevant.
- Filters: local date range (`from`, `to`, inclusive, in the user's timezone), `project_id`, `tag`.
- Local time is `start_time + tz_offset_minutes` (see [focus-sessions.md](focus-sessions.md#time-zones)).

## Definitions

| Metric | Definition |
|---|---|
| Focus time | sum of `active_duration_s` |
| Active days | local dates with at least one work session |
| Average daily focus | focus time ÷ active days |
| Session length | mean, median and longest active duration |
| Completion rate | completed ÷ (completed + stopped + unknown). Skipped and switched sessions are left out: they say nothing about finishing. |
| Interruption rate | share of sessions with any paused time (or a recorded pause) |
| Task completion rate | of tasks due or planned within the range (approved, not recurring templates), the share completed |
| Planned vs actual | for completed tasks with an estimate: sum of estimates vs sum of logged focus |

## Breakdowns

- **Timeseries**: focus per day, week or month, zero-filled. The UI picks the granularity from the range.
- **By hour**: each session's active minutes are spread across the local hours it covered, in proportion
  (a 09:40–10:20 session adds 20 min to 09:00 and 20 min to 10:00). Sessions *started* per hour, with
  their average length and completion rate, are reported alongside.
- **By weekday**: total focus and **average per calendar day**, which counts weekdays in the range that had no
  sessions. A weekday that appears twice in the range but was worked once averages half.
- **By project / by tag**: minutes and share. A session with several tags counts toward each tag, so tag
  shares can add up to more than 100 %. Untagged time shows as `(untagged)`.
- **Gaps**: average and median minutes between consecutive work sessions on the same local day.

## Observed patterns

`/api/analytics/patterns` returns plain-language findings, each only when there is enough data
(`personalization.min_samples`, default 5):

| id | Finding |
|---|---|
| `peak_window` | the 3-hour window holding the largest share of focus time |
| `session_length_by_daypart` | morning/afternoon/evening/night average session length, when the best is ≥ 1.2 × the worst |
| `completion_by_daypart` | completion rate by part of day, when the spread is ≥ 10 points |
| `weekday_focus` | most and least focused weekdays (per-calendar-day averages) |
| `interruptions` | share of sessions that included a pause |

## Estimation accuracy and planning multipliers

For each **completed** task with an estimate and logged focus time, `ratio = actual ÷ estimate`.
Grouped by category or project:

- `ratio` = Σ actual ÷ Σ estimate (the headline "estimated 60 → actual 87")
- `median_ratio` = median of per-task ratios (robust to one runaway task)
- `multiplier` = exp(w · median(log ratio)), with **w = 0 when n < min_samples**, otherwise
  w = n ÷ (n + prior_strength); clamped to [min_multiplier, max_multiplier]
- `confidence`: `insufficient` (n < min_samples), `moderate`, `strong` (n ≥ strong_samples)

Shrinkage keeps a handful of tasks from swinging plans: with the defaults (min 5, prior 10), five tasks
that each took twice as long give ×1.26, not ×2. The scheduler (Phase 4) looks multipliers up by
category, then project, then the overall value (`EstimationModel` in `estimation.py`). All parameters
are in Settings → Estimate learning.
