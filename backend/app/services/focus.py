"""Focus timer: a server-authoritative state machine for the single live session.

    start ──► running ──pause──► paused ──resume──► running
                 │                  │
                 └──── finish ──────┴──► finished (immutable history)

At most one session is live (running or paused). Durations:
``elapsed = end - start``, ``active = elapsed - paused``.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, ValidationFailed
from app.models import FocusSession
from app.models.enums import (
    ActionSource,
    EndReason,
    Outcome,
    SessionSource,
    SessionState,
    SessionType,
    TaskStatus,
)
from app.schemas.focus import FocusAnnotate, FocusFinish, FocusStart, FocusSwitch
from app.schemas.settings import UserSettings
from app.services import audit, tasks
from app.timeutil import offset_minutes

LIVE_STATES = (SessionState.running, SessionState.paused)


def _seconds(a: datetime, b: datetime) -> int:
    """Whole seconds from a to b, never negative (guards against clock skew)."""
    return max(0, int((b - a).total_seconds()))


def get_live(db: Session) -> FocusSession | None:
    return db.scalars(
        select(FocusSession).where(FocusSession.state.in_(LIVE_STATES), FocusSession.voided_at.is_(None))
    ).first()


def require_live(db: Session) -> FocusSession:
    live = get_live(db)
    if live is None:
        raise ConflictError("no focus session is running")
    return live


def paused_so_far(session: FocusSession, now: datetime) -> int:
    extra = _seconds(session.paused_since, now) if session.paused_since else 0
    return session.paused_duration_s + extra


def active_so_far(session: FocusSession, now: datetime) -> int:
    if session.state == SessionState.finished:
        return session.active_duration_s or 0
    return max(0, _seconds(session.start_time, now) - paused_so_far(session, now))


def _start(
    db: Session,
    task_id: uuid.UUID | None,
    type_: SessionType,
    planned_duration_s: int | None,
    notes: str | None,
    tags: list[str],
    now: datetime,
    settings: UserSettings,
    source: ActionSource,
) -> FocusSession:
    if get_live(db) is not None:
        raise ConflictError("a focus session is already live; finish or switch it first")
    task = None
    if task_id is not None:
        if type_ == SessionType.rest:
            raise ValidationFailed("rest sessions are not linked to a task")
        task = tasks.get_task(db, task_id)
        tasks.ensure_workable(db, task)
        tasks.mark_in_progress(db, task, source=source)
    session = FocusSession(
        id=uuid.uuid4(),
        task_id=task.id if task else None,
        type=type_,
        state=SessionState.running,
        source=SessionSource.timer,
        start_time=now,
        tz_offset_minutes=offset_minutes(settings.tz, now),
        planned_duration_s=planned_duration_s,
        paused_duration_s=0,
        pause_count=0,
        notes=notes,
        tags=list(tags),
        task_title_snapshot=task.title if task else None,
        project_id=task.project_id if task else None,
        category_snapshot=task.category if task else None,
    )
    db.add(session)
    db.flush()
    if source != ActionSource.user:
        audit.record(
            db,
            action="focus.started",
            source=source,
            entity_type="focus_session",
            entity_id=session.id,
            after={"task_id": session.task_id, "type": type_},
        )
    return session


def start(
    db: Session,
    data: FocusStart,
    now: datetime,
    settings: UserSettings,
    source: ActionSource = ActionSource.user,
) -> FocusSession:
    session = _start(
        db, data.task_id, data.type, data.planned_duration_s, data.notes, data.tags, now, settings, source
    )
    db.commit()
    return session


def pause(db: Session, now: datetime) -> FocusSession:
    session = require_live(db)
    if session.state != SessionState.running:
        raise ConflictError("session is not running")
    session.state = SessionState.paused
    session.paused_since = now
    session.pause_count = (session.pause_count or 0) + 1
    db.commit()
    return session


def resume(db: Session, now: datetime) -> FocusSession:
    session = require_live(db)
    if session.state != SessionState.paused:
        raise ConflictError("session is not paused")
    session.paused_duration_s = paused_so_far(session, now)
    session.paused_since = None
    session.state = SessionState.running
    db.commit()
    return session


def annotate(db: Session, data: FocusAnnotate) -> FocusSession:
    session = require_live(db)
    changes = data.model_dump(exclude_unset=True)
    if "notes" in changes:
        session.notes = changes["notes"]
    if changes.get("tags") is not None:
        session.tags = changes["tags"]
    db.commit()
    return session


def _finish(
    db: Session,
    session: FocusSession,
    end_reason: EndReason,
    now: datetime,
    *,
    outcome: Outcome | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> FocusSession:
    session.paused_duration_s = paused_so_far(session, now)
    session.paused_since = None
    session.end_time = max(now, session.start_time)
    elapsed = _seconds(session.start_time, session.end_time)
    session.paused_duration_s = min(session.paused_duration_s, elapsed)
    session.active_duration_s = elapsed - session.paused_duration_s
    session.state = SessionState.finished
    session.end_reason = end_reason
    if outcome is not None:
        session.outcome = outcome
    if notes is not None:
        session.notes = notes
    if tags is not None:
        session.tags = tags
    if elapsed == 0:
        session.quality_flags = ["zero_length"]
        session.exclude_from_stats = True
    db.flush()
    return session


def finish(
    db: Session, data: FocusFinish, now: datetime, source: ActionSource = ActionSource.user
) -> FocusSession:
    session = require_live(db)
    _finish(
        db, session, EndReason(data.end_reason), now, outcome=data.outcome, notes=data.notes, tags=data.tags
    )
    if session.task_id is not None:
        task = tasks.get_task(db, session.task_id)
        if data.complete_task:
            tasks.complete_task(db, task.id, now, source=source, commit=False)
        elif data.outcome == Outcome.blocked and tasks.is_open(task) and task.status != TaskStatus.blocked:
            audit.record(
                db,
                action="task.blocked",
                source=source,
                entity_type="task",
                entity_id=task.id,
                before={"status": task.status},
                after={"status": TaskStatus.blocked},
                reason="focus session finished with outcome 'blocked'",
            )
            task.status = TaskStatus.blocked
    if source != ActionSource.user:
        audit.record(
            db,
            action="focus.finished",
            source=source,
            entity_type="focus_session",
            entity_id=session.id,
            after={"end_reason": session.end_reason},
        )
    db.commit()
    return session


def switch(
    db: Session,
    data: FocusSwitch,
    now: datetime,
    settings: UserSettings,
    source: ActionSource = ActionSource.user,
) -> FocusSession:
    live = get_live(db)
    if live is not None:
        if live.task_id == data.task_id:
            raise ConflictError("already working on this task")
        # Validate the target before ending the current session, so a rejected switch changes nothing.
        tasks.ensure_workable(db, tasks.get_task(db, data.task_id))
        _finish(db, live, EndReason.switched, now)
    session = _start(db, data.task_id, data.type, data.planned_duration_s, None, [], now, settings, source)
    db.commit()
    return session


def discard(db: Session, now: datetime, source: ActionSource = ActionSource.user) -> None:
    """Delete a live session started by mistake. Finished sessions are voided via the sessions service."""
    session = require_live(db)
    audit.record(
        db,
        action="focus.discarded",
        source=source,
        entity_type="focus_session",
        entity_id=session.id,
        before=audit.snapshot(session),
        reason=f"discarded after {active_so_far(session, now)}s active",
    )
    db.delete(session)
    db.commit()
