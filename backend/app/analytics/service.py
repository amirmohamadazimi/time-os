"""Analytics service: loads data, calls the pure metric functions, adds metadata."""

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.analytics import estimation, metrics, patterns
from app.analytics.frame import Filters, SessionFrame, load
from app.models import Project, Task
from app.models.enums import SessionType, TaskStatus
from app.schemas.settings import UserSettings
from app.timeutil import day_bounds_utc


def meta(frame: SessionFrame) -> dict:
    return {
        "kind": "observed",
        "from": frame.filters.date_from,
        "to": frame.filters.date_to,
        "type": frame.filters.type.value if frame.filters.type else None,
        "session_count": len(frame.df),
        "excluded_count": frame.excluded_count,
    }


def task_completion(
    db: Session, settings: UserSettings, date_from: date | None, date_to: date | None
) -> dict:
    """Of tasks due or planned within the range, how many are completed."""
    stmt = select(Task.status).where(Task.recurrence_rule.is_(None), Task.pending_approval.is_(False))
    if date_from or date_to:
        lo = day_bounds_utc(date_from, settings.tz)[0] if date_from else None
        hi = day_bounds_utc(date_to, settings.tz)[1] if date_to else None
        due = Task.deadline.is_not(None)
        planned = Task.planned_date.is_not(None)
        if lo is not None:
            due &= Task.deadline >= lo
            planned &= Task.planned_date >= date_from
        if hi is not None:
            due &= Task.deadline < hi
            planned &= Task.planned_date <= date_to
        stmt = stmt.where(or_(due, planned))
    statuses = list(db.scalars(stmt))
    considered = [s for s in statuses if s != TaskStatus.cancelled]
    done = sum(1 for s in considered if s == TaskStatus.completed)
    return {
        "tasks_considered": len(considered),
        "tasks_completed": done,
        "task_completion_rate": round(done / len(considered), 3) if considered else None,
    }


def summary(db: Session, settings: UserSettings, filters: Filters) -> dict:
    work = load(db, settings, Filters(**{**filters.__dict__, "type": SessionType.work}))
    rest = load(db, settings, Filters(**{**filters.__dict__, "type": SessionType.rest}))
    obs = estimation.observations(db)
    planned_vs_actual = {
        "tasks": len(obs),
        "estimated_minutes": round(sum(o.estimate_minutes for o in obs), 1),
        "actual_minutes": round(sum(o.actual_minutes for o in obs), 1),
    }
    return {
        "meta": meta(work),
        **metrics.summary(work.df, rest.df),
        **task_completion(db, settings, filters.date_from, filters.date_to),
        "planned_vs_actual": planned_vs_actual,
    }


def timeseries(db: Session, settings: UserSettings, filters: Filters, granularity: str) -> dict:
    frame = load(db, settings, filters)
    return {
        "meta": meta(frame),
        "granularity": granularity,
        "items": metrics.timeseries(frame.df, granularity, filters.date_from, filters.date_to),
    }


def by_hour(db: Session, settings: UserSettings, filters: Filters) -> dict:
    frame = load(db, settings, filters)
    return {"meta": meta(frame), "items": metrics.by_hour(frame.df)}


def by_weekday(db: Session, settings: UserSettings, filters: Filters) -> dict:
    frame = load(db, settings, filters)
    return {"meta": meta(frame), "items": metrics.by_weekday(frame.df, filters.date_from, filters.date_to)}


def by_project(db: Session, settings: UserSettings, filters: Filters) -> dict:
    frame = load(db, settings, filters)
    names = dict(db.execute(select(Project.id, Project.name)).all())
    items = [
        {
            "project_id": r["key"],
            "project_name": names.get(r["key"], "(no project)"),
            **{k: r[k] for k in ("focus_minutes", "share", "sessions")},
        }
        for r in metrics.by_key(frame.df, "project_id")
    ]
    return {"meta": meta(frame), "items": items}


def by_tag(db: Session, settings: UserSettings, filters: Filters) -> dict:
    frame = load(db, settings, filters)
    return {"meta": meta(frame), "items": metrics.by_tag(frame.df)}


def gaps(db: Session, settings: UserSettings, filters: Filters) -> dict:
    frame = load(db, settings, filters)
    return {"meta": meta(frame), **metrics.gaps(frame.df)}


def estimation_accuracy(db: Session, settings: UserSettings, group_by: str) -> dict:
    obs = estimation.observations(db)
    p = settings.personalization
    return {
        "meta": {
            "kind": "observed",
            "tasks": len(obs),
            "min_samples": p.min_samples,
            "strong_samples": p.strong_samples,
        },
        "items": estimation.group(obs, group_by, p),
    }


def find_patterns(db: Session, settings: UserSettings, filters: Filters) -> dict:
    frame = load(db, settings, filters)
    items = patterns.find_patterns(
        frame.df, settings.personalization.min_samples, filters.date_from, filters.date_to
    )
    return {"meta": meta(frame), "items": items}
