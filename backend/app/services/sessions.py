"""Historical focus sessions: listing, manual logging, annotation and voiding."""

import uuid
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationFailed
from app.models import FocusSession, Project
from app.models.enums import ActionSource, SessionSource, SessionState, SessionType
from app.schemas.focus import ManualSessionCreate, SessionAnnotate
from app.schemas.settings import UserSettings
from app.services import audit, tasks
from app.timeutil import day_bounds_utc, offset_minutes


def get_session(db: Session, session_id: uuid.UUID) -> FocusSession:
    session = db.get(FocusSession, session_id)
    if session is None:
        raise NotFoundError(f"session {session_id} not found")
    return session


def list_sessions(
    db: Session,
    settings: UserSettings,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    type_: SessionType | None = None,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
    source: SessionSource | None = None,
    include_excluded: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[FocusSession], int]:
    stmt = select(FocusSession).where(
        FocusSession.state == SessionState.finished, FocusSession.voided_at.is_(None)
    )
    if date_from:
        stmt = stmt.where(FocusSession.start_time >= day_bounds_utc(date_from, settings.tz)[0])
    if date_to:
        stmt = stmt.where(FocusSession.start_time < day_bounds_utc(date_to, settings.tz)[1])
    if type_:
        stmt = stmt.where(FocusSession.type == type_)
    if task_id:
        stmt = stmt.where(FocusSession.task_id == task_id)
    if project_id:
        stmt = stmt.where(FocusSession.project_id == project_id)
    if source:
        stmt = stmt.where(FocusSession.source == source)
    if not include_excluded:
        stmt = stmt.where(FocusSession.exclude_from_stats.is_(False))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(FocusSession.notes).like(like),
                func.lower(FocusSession.task_title_snapshot).like(like),
            )
        )
    stmt = stmt.order_by(FocusSession.start_time.desc())
    if tag:
        wanted = tag.lower()
        rows = [s for s in db.scalars(stmt).unique() if any(t.lower() == wanted for t in s.tags or [])]
        return rows[offset : offset + limit], len(rows)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(limit).offset(offset)).unique())
    return rows, total


def _overlapping(db: Session, start: datetime, end: datetime) -> FocusSession | None:
    return db.scalars(
        select(FocusSession).where(
            FocusSession.voided_at.is_(None),
            FocusSession.state == SessionState.finished,
            FocusSession.start_time < end,
            FocusSession.end_time > start,
        )
    ).first()


def create_manual(
    db: Session,
    data: ManualSessionCreate,
    now: datetime,
    settings: UserSettings,
    source: ActionSource = ActionSource.user,
) -> FocusSession:
    if data.end_time > now:
        raise ValidationFailed("cannot log a session that ends in the future")
    task = None
    if data.task_id:
        if data.type == SessionType.rest:
            raise ValidationFailed("rest sessions are not linked to a task")
        task = tasks.get_task(db, data.task_id)
        if task.is_template:
            raise ValidationFailed("log time on an occurrence, not on a recurring template")
    clash = _overlapping(db, data.start_time, data.end_time)
    if clash:
        raise ConflictError("overlaps an existing session", details={"session_id": str(clash.id)})
    elapsed = int((data.end_time - data.start_time).total_seconds())
    session = FocusSession(
        id=uuid.uuid4(),
        task_id=task.id if task else None,
        type=data.type,
        state=SessionState.finished,
        source=SessionSource.manual,
        start_time=data.start_time,
        end_time=data.end_time,
        tz_offset_minutes=offset_minutes(settings.tz, data.start_time),
        active_duration_s=elapsed - data.paused_duration_s,
        paused_duration_s=data.paused_duration_s,
        end_reason=data.end_reason,
        outcome=data.outcome,
        notes=data.notes,
        tags=data.tags,
        task_title_snapshot=task.title if task else None,
        project_id=task.project_id if task else None,
        category_snapshot=task.category if task else None,
    )
    db.add(session)
    db.flush()
    audit.record(
        db,
        action="session.logged",
        source=source,
        entity_type="focus_session",
        entity_id=session.id,
        after=audit.snapshot(session),
    )
    db.commit()
    return session


def annotate(
    db: Session, session_id: uuid.UUID, data: SessionAnnotate, source: ActionSource = ActionSource.user
) -> FocusSession:
    session = get_session(db, session_id)
    if session.state != SessionState.finished:
        raise ConflictError("edit the live session through the focus timer")
    if session.voided_at is not None:
        raise ConflictError("session has been deleted")
    before = audit.snapshot(session)
    changes = data.model_dump(exclude_unset=True)
    if "task_id" in changes:
        task_id = changes.pop("task_id")
        if task_id is None:
            session.task_id = None
        else:
            if session.type == SessionType.rest:
                raise ValidationFailed("rest sessions are not linked to a task")
            task = tasks.get_task(db, task_id)
            session.task_id = task.id
            session.task_title_snapshot = task.title
            session.category_snapshot = task.category
            if "project_id" not in changes:
                session.project_id = task.project_id
    if "project_id" in changes:
        project_id = changes.pop("project_id")
        if project_id is not None and db.get(Project, project_id) is None:
            raise ValidationFailed(f"project {project_id} does not exist")
        session.project_id = project_id
    for key in ("notes", "outcome"):
        if key in changes:
            setattr(session, key, changes[key])
    if changes.get("tags") is not None:
        session.tags = changes["tags"]
    if changes.get("exclude_from_stats") is not None:
        session.exclude_from_stats = changes["exclude_from_stats"]
    db.flush()
    b, a = audit.diff(before, audit.snapshot(session))
    if a:
        audit.record(
            db,
            action="session.annotated",
            source=source,
            entity_type="focus_session",
            entity_id=session.id,
            before=b,
            after=a,
        )
    db.commit()
    return session


def void(db: Session, session_id: uuid.UUID, now: datetime, source: ActionSource = ActionSource.user) -> None:
    session = get_session(db, session_id)
    if session.state != SessionState.finished:
        raise ConflictError("discard the live session through the focus timer")
    if session.voided_at is not None:
        return
    before = audit.snapshot(session)
    session.voided_at = now
    audit.record(
        db,
        action="session.voided",
        source=source,
        entity_type="focus_session",
        entity_id=session.id,
        before=before,
        after={"voided_at": now},
    )
    db.commit()
