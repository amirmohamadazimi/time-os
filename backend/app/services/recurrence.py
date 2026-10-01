"""Recurring tasks: a task with ``recurrence_rule`` is a template; occurrences are ordinary tasks.

Rules are RFC 5545 RRULE strings, e.g. ``FREQ=DAILY``, ``FREQ=WEEKLY;BYDAY=MO,WE,TH,SA``,
``FREQ=MONTHLY;BYMONTHDAY=1``. Generation is idempotent thanks to the unique
``(recurrence_parent_id, occurrence_date)`` constraint.
"""

from datetime import date, datetime, time, timedelta

from dateutil.rrule import rrulestr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ValidationFailed
from app.models import Task
from app.models.enums import ActionSource, TaskSource, TaskStatus
from app.schemas.settings import UserSettings
from app.services import audit
from app.timeutil import local_date

MAX_WINDOW_DAYS = 366


def normalize_rule(rule: str) -> str:
    """Validate an RRULE and return it without an ``RRULE:`` prefix."""
    cleaned = rule.strip()
    if cleaned.upper().startswith("RRULE:"):
        cleaned = cleaned[6:]
    cleaned = cleaned.upper().replace(" ", "")
    if "DTSTART" in cleaned or "\n" in cleaned or "RRULE:" in cleaned:
        raise ValidationFailed("recurrence_rule must be a single RRULE without DTSTART")
    if not cleaned.startswith("FREQ=") and ";FREQ=" not in cleaned:
        raise ValidationFailed("recurrence_rule must contain FREQ (e.g. FREQ=DAILY)")
    try:
        rrulestr(cleaned, dtstart=datetime(2000, 1, 1))
    except (ValueError, TypeError) as exc:
        raise ValidationFailed(f"invalid recurrence_rule: {exc}") from exc
    return cleaned


def anchor_date(template: Task, settings: UserSettings) -> date:
    if template.planned_date:
        return template.planned_date
    if template.earliest_start:
        return local_date(template.earliest_start, settings.tz)
    return local_date(template.created_at, settings.tz)


def occurrence_dates(rule: str, anchor: date, start: date, end: date) -> list[date]:
    """Dates in [start, end] on which ``rule`` (anchored at ``anchor``) occurs."""
    if end < start:
        return []
    rset = rrulestr(rule, dtstart=datetime.combine(anchor, time(0)))
    lo = datetime.combine(max(start, anchor), time(0))
    hi = datetime.combine(end, time(0))
    return [d.date() for d in rset.between(lo, hi, inc=True)]


def generate_occurrences(
    db: Session, start: date, end: date, settings: UserSettings, commit: bool = True
) -> list[Task]:
    if end < start:
        raise ValidationFailed("end_date must not be before start_date")
    if (end - start) > timedelta(days=MAX_WINDOW_DAYS):
        raise ValidationFailed(f"window is limited to {MAX_WINDOW_DAYS} days")
    templates = db.scalars(
        select(Task).where(
            Task.recurrence_rule.is_not(None),
            Task.status.not_in([TaskStatus.cancelled, TaskStatus.completed]),
            Task.pending_approval.is_(False),
        )
    ).all()
    created: list[Task] = []
    for template in templates:
        dates = occurrence_dates(template.recurrence_rule, anchor_date(template, settings), start, end)
        if not dates:
            continue
        existing = set(
            db.scalars(
                select(Task.occurrence_date).where(
                    Task.recurrence_parent_id == template.id, Task.occurrence_date.in_(dates)
                )
            )
        )
        for day in dates:
            if day in existing:
                continue
            occurrence = Task(
                title=template.title,
                description=template.description,
                project_id=template.project_id,
                category=template.category,
                priority=template.priority,
                status=TaskStatus.planned,
                estimated_minutes=template.estimated_minutes,
                planned_date=day,
                preferred_time=template.preferred_time,
                energy_requirement=template.energy_requirement,
                importance=template.importance,
                urgency=template.urgency,
                tags=list(template.tags or []),
                source=TaskSource.recurrence,
                recurrence_parent_id=template.id,
                occurrence_date=day,
            )
            db.add(occurrence)
            created.append(occurrence)
    if created:
        db.flush()
        audit.record(
            db,
            action="recurrence.generated",
            source=ActionSource.system,
            entity_type="task",
            after={"count": len(created), "start": start, "end": end},
        )
    if commit:
        db.commit()
    return created
