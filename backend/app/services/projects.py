import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models import FocusSession, Project, Task
from app.models.enums import OPEN_TASK_STATUSES, ActionSource, ProjectStatus, SessionState, SessionType, TaskStatus
from app.schemas.project import ProjectCreate, ProjectStats, ProjectUpdate
from app.services import audit


def list_projects(db: Session, status: ProjectStatus | None = None) -> list[Project]:
    stmt = select(Project).order_by(Project.name)
    if status:
        stmt = stmt.where(Project.status == status)
    return list(db.scalars(stmt))


def get_project(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"project {project_id} not found")
    return project


def _commit_unique(db: Session, name: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"a project named '{name}' already exists") from exc


def create_project(db: Session, data: ProjectCreate, source: ActionSource = ActionSource.user) -> Project:
    name = data.name.strip()
    _name_free(db, name)
    project = Project(name=name, description=data.description, color=data.color)
    db.add(project)
    db.flush()
    audit.record(
        db, action="project.created", source=source, entity_type="project", entity_id=project.id,
        after=audit.snapshot(project),
    )
    _commit_unique(db, project.name)
    return project


def _name_free(db: Session, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Project.id).where(func.lower(Project.name) == name.lower())
    if exclude:
        stmt = stmt.where(Project.id != exclude)
    if db.scalar(stmt) is not None:
        raise ConflictError(f"a project named '{name}' already exists")


def update_project(
    db: Session, project_id: uuid.UUID, data: ProjectUpdate, source: ActionSource = ActionSource.user
) -> Project:
    project = get_project(db, project_id)
    before = audit.snapshot(project)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()
        _name_free(db, changes["name"], exclude=project.id)
    for key, value in changes.items():
        if key in ("name", "status") and value is None:
            continue
        setattr(project, key, value)
    db.flush()
    b, a = audit.diff(before, audit.snapshot(project))
    if a:
        audit.record(db, action="project.updated", source=source, entity_type="project", entity_id=project.id,
                     before=b, after=a)
    _commit_unique(db, project.name)
    return project


def delete_project(db: Session, project_id: uuid.UUID, source: ActionSource = ActionSource.user) -> None:
    project = get_project(db, project_id)
    tasks = db.scalar(select(func.count()).select_from(Task).where(Task.project_id == project_id))
    sessions = db.scalar(
        select(func.count()).select_from(FocusSession).where(FocusSession.project_id == project_id)
    )
    if tasks or sessions:
        raise ConflictError(
            "project has tasks or focus history; archive it instead to keep analytics intact",
            details={"tasks": tasks, "sessions": sessions},
        )
    audit.record(db, action="project.deleted", source=source, entity_type="project", entity_id=project.id,
                 before=audit.snapshot(project))
    db.delete(project)
    db.commit()


def project_stats(db: Session, project_id: uuid.UUID) -> ProjectStats:
    get_project(db, project_id)
    focus = db.execute(
        select(
            func.coalesce(func.sum(FocusSession.active_duration_s), 0),
            func.count(FocusSession.id),
            func.max(FocusSession.end_time),
        ).where(
            FocusSession.project_id == project_id,
            FocusSession.type == SessionType.work,
            FocusSession.state == SessionState.finished,
            FocusSession.voided_at.is_(None),
        )
    ).one()
    completed = db.scalar(
        select(func.count()).select_from(Task).where(
            Task.project_id == project_id, Task.status == TaskStatus.completed, Task.recurrence_rule.is_(None)
        )
    )
    remaining = db.execute(
        select(func.count(), func.coalesce(func.sum(Task.estimated_minutes), 0)).where(
            Task.project_id == project_id,
            Task.status.in_(OPEN_TASK_STATUSES),
            Task.recurrence_rule.is_(None),
            Task.pending_approval.is_(False),
        )
    ).one()
    last: datetime | None = focus[2]
    return ProjectStats(
        project_id=project_id,
        total_focus_minutes=round(focus[0] / 60, 1),
        session_count=focus[1],
        tasks_completed=completed or 0,
        tasks_remaining=remaining[0],
        estimated_remaining_minutes=int(remaining[1]),
        last_worked_at=last,
    )
