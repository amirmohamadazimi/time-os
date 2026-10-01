"""Today view. Until the Phase 4 scheduler produces time blocks, 'planned' means tasks planned
for or due today, and 'next' is ordered by overdue, deadline, priority and importance."""

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import FocusSession, Task
from app.models.enums import OPEN_TASK_STATUSES, Priority, SessionState, SessionType, TaskStatus
from app.schemas.dashboard import TodayDashboard
from app.schemas.focus import FocusSessionOut, LiveSessionOut
from app.schemas.settings import UserSettings
from app.services import focus, recurrence, tasks
from app.timeutil import day_bounds_utc, local_date

PRIORITY_RANK = {Priority.critical: 0, Priority.high: 1, Priority.medium: 2, Priority.low: 3}
NEXT_LIMIT = 8


def today(db: Session, now: datetime, settings: UserSettings) -> TodayDashboard:
    tz = settings.tz
    day = local_date(now, tz)
    start, end = day_bounds_utc(day, tz)
    recurrence.generate_occurrences(db, day, day + timedelta(days=6), settings)

    finished = db.execute(
        select(FocusSession.type, func.coalesce(func.sum(FocusSession.active_duration_s), 0), func.count())
        .where(
            FocusSession.state == SessionState.finished,
            FocusSession.voided_at.is_(None),
            FocusSession.exclude_from_stats.is_(False),
            FocusSession.start_time >= start,
            FocusSession.start_time < end,
        )
        .group_by(FocusSession.type)
    ).all()
    seconds = {t: secs for t, secs, _ in finished}
    count = sum(n for _, _, n in finished)
    live = focus.get_live(db)
    live_out = None
    if live:
        active = focus.active_so_far(live, now)
        seconds[live.type] = seconds.get(live.type, 0) + active
        live_out = LiveSessionOut(
            **FocusSessionOut.model_validate(live).model_dump(), server_time=now, active_so_far_s=active
        )

    open_tasks = (
        db.scalars(
            select(Task).where(
                Task.status.in_(OPEN_TASK_STATUSES),
                Task.recurrence_rule.is_(None),
                Task.pending_approval.is_(False),
                or_(Task.planned_date <= day, Task.deadline < end, Task.status == TaskStatus.in_progress),
            )
        )
        .unique()
        .all()
    )
    actual = tasks.actual_minutes_by_task(db, [t.id for t in open_tasks])
    blocked = tasks.unresolved_strict_prerequisites(db, [t.id for t in open_tasks])

    def key(t: Task):
        overdue = t.deadline is not None and t.deadline < now
        return (
            not overdue,
            t.status != TaskStatus.in_progress,
            t.deadline or datetime.max.replace(tzinfo=tz),
            PRIORITY_RANK[t.priority],
            -(t.importance or 0),
            t.created_at,
        )

    ordered = sorted(open_tasks, key=key)
    today_tasks = [
        t for t in ordered if (t.planned_date == day) or (t.deadline and start <= t.deadline < end)
    ]
    planned = sum(max(0.0, (t.estimated_minutes or 0) - actual.get(t.id, 0.0)) for t in today_tasks)
    workable = [t for t in ordered if t.id not in blocked and t.status != TaskStatus.blocked]

    def count_where(*conds) -> int:
        return (
            db.scalar(select(func.count()).select_from(Task).where(Task.recurrence_rule.is_(None), *conds))
            or 0
        )

    return TodayDashboard(
        date=day,
        timezone=settings.timezone,
        focused_minutes=round(seconds.get(SessionType.work, 0) / 60, 1),
        rest_minutes=round(seconds.get(SessionType.rest, 0) / 60, 1),
        planned_minutes=round(planned, 1),
        sessions_today=count,
        current_session=live_out,
        next_tasks=tasks.to_out(db, workable[:NEXT_LIMIT]),
        due_today=tasks.to_out(db, [t for t in ordered if t.deadline and start <= t.deadline < end]),
        overdue=tasks.to_out(db, [t for t in ordered if t.deadline and t.deadline < now]),
        inbox_count=count_where(Task.status == TaskStatus.inbox, Task.pending_approval.is_(False)),
        pending_approval_count=count_where(Task.pending_approval.is_(True)),
    )
