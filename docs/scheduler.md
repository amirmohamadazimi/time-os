# Scheduling engine

The scheduler is ordinary, deterministic application code. Claude never decides where a
block goes; it can ask the engine for a plan, explain the engine's reasons, or propose a change
that the engine then validates.

The interface is defined in [`backend/app/scheduler/types.py`](../backend/app/scheduler/types.py)
(Phase 1 contract; the engine itself is Phase 4).

## Contract

```python
def generate_schedule(request: ScheduleRequest) -> ScheduleResult: ...
def validate_blocks(request: ScheduleRequest, blocks: Sequence[ProposedBlock]) -> list[Violation]: ...
def reschedule(request: ScheduleRequest, current: Sequence[ScheduledBlock], event: RescheduleEvent) -> RescheduleResult: ...
```

All three are **pure functions**: the same request always produces the same result. The
service layer gathers the inputs from the database (tasks, calendar cache, settings, historical
model, existing blocks), calls the engine, then persists and audits the result. That makes
every rule unit-testable without a database or clock.

### Inputs (`ScheduleRequest`)
* `horizon`: the window to plan (usually one local day) and `now` (nothing is placed in the past).
* `tasks`: `SchedulableTask` (remaining minutes, deadline, earliest start, priority,
  importance, urgency, preferred time, energy, strict dependencies, planned date, status).
* `busy`: `BusyInterval` from calendar events, meals and personal commitments.
* `fixed_blocks`: blocks that must not move (locked by the user, already done, or in the past).
* `preferences`: working hours, break policy, buffer ratio, transition time, minimum block,
  maximum continuous focus.
* `history`: `HistoricalModel` (estimation multipliers with sample sizes, focus quality by hour).

### Outputs (`ScheduleResult`)
* `blocks`: task, break and buffer blocks, each with `reasons: list[Reason]`.
* `unscheduled`: tasks that did not fit, each with a reason code
  (`no_capacity`, `deadline_unreachable`, `blocked_by_dependency`, `not_yet_startable`,
  `below_min_block`).
* `capacity`: `CapacityReport` with available, reserved, fillable and required minutes, and
  `overflow_minutes`. When required work exceeds capacity the report says so explicitly and
  lists `recommendations` (which tasks to move and to where). The engine never pretends
  everything fits.

## Algorithm (Phase 4)

1. **Availability.** Start from working hours in the horizon, clip to `now`, subtract busy
   intervals and fixed blocks. Result: free windows.
2. **Reserve, don't fill.** Hold back `buffer_ratio` of free time for interruptions (default
   15%), insert `break_minutes` after at most `max_focus_minutes` of continuous work, add
   `transition_minutes` between blocks of different tasks, and keep meal windows free. Windows
   shorter than `min_block_minutes` stay unscheduled; deliberate free time is a feature.
3. **Effective estimates.** `remaining = max(0, estimate × multiplier − logged)`, where the
   multiplier comes from the historical model (category, then project, then global) and is
   shrunk toward 1.0 when there are few samples (see [analytics.md](analytics.md)).
4. **Eligibility.** Exclude templates, AI proposals awaiting approval, completed, cancelled and
   `blocked` tasks; tasks whose strict prerequisites are not done (unless the prerequisite is
   scheduled earlier in the same plan); tasks whose `earliest_start` is after the horizon.
5. **Scoring.** A weighted sum with every term recorded as a `Reason`:
   deadline pressure (slack between now and deadline after remaining work), priority,
   importance, urgency, planned for today, already in progress (less context switching),
   and age. Weights live in preferences, not in code paths.
6. **Placement.** Greedy by score, earliest feasible window first, with preferences for
   matching `preferred_time` and placing `energy_requirement=high` tasks in the user's
   historically strongest hours. Long tasks split into chunks no smaller than
   `min_block_minutes`. A block never ends after its task's deadline.
7. **Capacity report and recommendations.** Required work = remaining work of tasks due within
   the horizon plus tasks planned for it. If it exceeds fillable capacity, the lowest-scoring
   movable tasks are recommended for the next day with free capacity.

## Validation

`validate_blocks` is used for every externally proposed block, whether from the UI drag-and-drop
or from a Claude tool call. It checks that the task exists and is schedulable, the duration
is positive, the block is inside the horizon, does not overlap busy time or fixed blocks,
starts after `earliest_start`, ends before `deadline`, and respects strict dependencies.
A violation list is returned; nothing is persisted unless it is empty.

## Dynamic rescheduling

`RescheduleEvent` variants: `TaskOverrun(task_id, observed_minutes)`,
`NewBusyInterval(interval)`, `BlockSkipped(block_id)`, `TaskFinishedEarly(task_id)`.
Past, done and locked blocks are fixed; the rest of the horizon is re-planned with the same
engine, and the result is a diff (`moved`, `shortened`, `dropped`, `added`) with reasons.

Example: at 09:50 a 60-minute Python block that started at 09:00 is unfinished. The focus
timer reports 50 minutes used and an outcome of "not done", so the service emits
`TaskOverrun`. The engine proposes extending Python by 30 minutes and moving German later. In
`suggest` mode the diff is shown to the user; in `auto` mode it is applied and written to the
audit log with the reason.

## Explainability

Every block carries the reasons that produced it, for example:

```
Quant Research 09:00–10:30
• deadline tomorrow 18:00 (slack 4h)          +40
• priority high                                +20
• 90 min free in your strongest hours           +10
• historically takes ~85 min (multiplier 1.4, 12 samples)
```

Claude's "why" answers quote these reasons; it does not invent new ones.

## Tests (Phase 4)

Calendar conflicts, deadline constraints, insufficient time (explicit overflow), strict and
soft dependencies, break and buffer insertion, preferred-time placement, splitting,
rescheduling diffs, and timezone/DST horizons.
