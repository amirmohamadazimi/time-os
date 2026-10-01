"""Task management: CRUD, status transitions, dependencies, inbox capture, provenance."""

import re
import uuid
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationFailed
from app.models import FocusSession, Project, Task, TaskDependency
from app.models.enums import (
    OPEN_TASK_STATUSES,
    ActionSource,
    SessionState,
    SessionType,
    TaskSource,
    TaskStatus,
)
from app.schemas.task import DependencyIn, TaskCreate, TaskOut, TaskUpdate
from app.services import audit
from app.services.recurrence import normalize_rule

RESOLVED_STATUSES = (TaskStatus.completed, TaskStatus.cancelled)
_BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)]|\[[ xX]?\])\s*")


def get_task(db: Session, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"task {task_id} not found")
    return task


def list_tasks(
    db: Session,
    *,
    statuses: list[TaskStatus] | None = None,
    project_id: uuid.UUID | None = None,
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    planned_date: date | None = None,
    due_before: datetime | None = None,
    pending_approval: bool | None = None,
    include_templates: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[Task]:
    stmt = select(Task)
    if statuses:
        stmt = stmt.where(Task.status.in_(statuses))
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if category:
        stmt = stmt.where(func.lower(Task.category) == category.lower())
    if planned_date:
        stmt = stmt.where(Task.planned_date == planned_date)
    if due_before:
        stmt = stmt.where(Task.deadline.is_not(None), Task.deadline < due_before)
    if pending_approval is not None:
        stmt = stmt.where(Task.pending_approval.is_(pending_approval))
    if not include_templates:
        stmt = stmt.where(Task.recurrence_rule.is_(None))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Task.title).like(like), func.lower(Task.description).like(like)))
    stmt = stmt.order_by(
        Task.deadline.is_(None),
        Task.deadline,
        Task.planned_date.is_(None),
        Task.planned_date,
        Task.created_at,
    )
    tasks = list(db.scalars(stmt).unique())
    if tag:
        # JSON containment differs across SQLite/PostgreSQL; tag sets are small, so filter in Python.
        wanted = tag.lower()
        tasks = [t for t in tasks if any(x.lower() == wanted for x in t.tags or [])]
    return tasks[offset : offset + limit]


def search_tasks(db: Session, query: str, limit: int = 20) -> list[Task]:
    """Text search over title, description, category and tags (open tasks first)."""
    needle = query.strip().lower()
    if not needle:
        return []
    candidates = db.scalars(select(Task).where(Task.recurrence_rule.is_(None))).unique().all()

    def matches(t: Task) -> bool:
        hay = " ".join([t.title, t.description or "", t.category or "", " ".join(t.tags or [])]).lower()
        return all(word in hay for word in needle.split())

    found = [t for t in candidates if matches(t)]
    found.sort(key=lambda t: (t.status in RESOLVED_STATUSES, t.deadline is None, t.deadline or t.created_at))
    return found[:limit]


def categories(db: Session) -> list[str]:
    rows = db.scalars(select(Task.category).where(Task.category.is_not(None)).distinct())
    return sorted({c for c in rows if c}, key=str.lower)


# ---------------------------------------------------------------- validation helpers


def _check_project(db: Session, project_id: uuid.UUID | None) -> None:
    if project_id is not None and db.get(Project, project_id) is None:
        raise ValidationFailed(f"project {project_id} does not exist")


def _check_window(earliest: datetime | None, deadline: datetime | None) -> None:
    if earliest and deadline and earliest > deadline:
        raise ValidationFailed("earliest_start must not be after deadline")


def _would_cycle(db: Session, task_id: uuid.UUID, prerequisites: list[uuid.UUID]) -> bool:
    """True if making ``task_id`` depend on ``prerequisites`` closes a cycle."""
    graph: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for dep in db.scalars(select(TaskDependency).where(TaskDependency.task_id != task_id)):
        graph[dep.task_id].add(dep.depends_on_id)
    stack, seen = list(prerequisites), set()
    while stack:
        node = stack.pop()
        if node == task_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph[node])
    return False


def _set_dependencies(db: Session, task: Task, deps: list[DependencyIn]) -> None:
    by_id: dict[uuid.UUID, bool] = {}
    for dep in deps:
        if dep.depends_on_id == task.id:
            raise ValidationFailed("a task cannot depend on itself")
        by_id[dep.depends_on_id] = by_id.get(dep.depends_on_id, False) or dep.strict
    if by_id:
        found = set(db.scalars(select(Task.id).where(Task.id.in_(list(by_id)))))
        missing = [str(i) for i in by_id if i not in found]
        if missing:
            raise ValidationFailed("dependency tasks do not exist", details={"missing": missing})
        if _would_cycle(db, task.id, list(by_id)):
            raise ValidationFailed("dependencies would create a cycle")
    task.dependencies = [
        TaskDependency(task_id=task.id, depends_on_id=dep_id, strict=strict)
        for dep_id, strict in by_id.items()
    ]


def _apply_status(task: Task, status: TaskStatus, now: datetime) -> None:
    if status == TaskStatus.completed and task.status != TaskStatus.completed:
        task.completed_at = now
    elif status != TaskStatus.completed:
        task.completed_at = None
    task.status = status


def _snapshot(task: Task) -> dict:
    snap = audit.snapshot(task)
    snap["dependencies"] = sorted(
        ({"depends_on_id": str(d.depends_on_id), "strict": d.strict} for d in task.dependencies),
        key=lambda d: d["depends_on_id"],
    )
    return snap


# ---------------------------------------------------------------- mutations


def create_task(
    db: Session,
    data: TaskCreate,
    now: datetime,
    *,
    source: ActionSource = ActionSource.user,
    pending_approval: bool = False,
    reason: str | None = None,
    commit: bool = True,
) -> Task:
    _check_project(db, data.project_id)
    _check_window(data.earliest_start, data.deadline)
    fields = data.model_dump(exclude={"dependencies", "status"})
    if fields.get("recurrence_rule"):
        fields["recurrence_rule"] = normalize_rule(fields["recurrence_rule"])
    if fields.get("category"):
        fields["category"] = fields["category"].strip() or None
    task = Task(
        id=uuid.uuid4(),
        **fields,
        source=TaskSource.ai if source == ActionSource.ai else TaskSource.user,
        pending_approval=pending_approval,
    )
    _apply_status(task, data.status, now)
    db.add(task)
    db.flush()
    _set_dependencies(db, task, data.dependencies)
    db.flush()
    audit.record(
        db,
        action="task.created",
        source=source,
        entity_type="task",
        entity_id=task.id,
        after=_snapshot(task),
        reason=reason,
    )
    if commit:
        db.commit()
    return task


def update_task(
    db: Session,
    task_id: uuid.UUID,
    data: TaskUpdate,
    now: datetime,
    *,
    source: ActionSource = ActionSource.user,
    reason: str | None = None,
) -> Task:
    task = get_task(db, task_id)
    before = _snapshot(task)
    changes = data.model_dump(exclude_unset=True)
    for required in ("title", "priority", "status", "tags"):
        if required in changes and changes[required] is None:
            raise ValidationFailed(f"{required} cannot be null")
    if "project_id" in changes:
        _check_project(db, changes["project_id"])
    if changes.get("recurrence_rule"):
        if task.recurrence_parent_id is not None:
            raise ValidationFailed("an occurrence of a recurring task cannot itself recur")
        changes["recurrence_rule"] = normalize_rule(changes["recurrence_rule"])
    _check_window(changes.get("earliest_start", task.earliest_start), changes.get("deadline", task.deadline))
    deps = changes.pop("dependencies", None)
    status = changes.pop("status", None)
    for key, value in changes.items():
        setattr(task, key, value)
    if status is not None:
        _apply_status(task, status, now)
    if deps is not None:
        _set_dependencies(db, task, [DependencyIn(**d) for d in deps])
    db.flush()
    b, a = audit.diff(before, _snapshot(task))
    if a:
        audit.record(
            db,
            action="task.updated",
            source=source,
            entity_type="task",
            entity_id=task.id,
            before=b,
            after=a,
            reason=reason,
        )
    db.commit()
    return task


def complete_task(
    db: Session,
    task_id: uuid.UUID,
    now: datetime,
    *,
    source: ActionSource = ActionSource.user,
    commit: bool = True,
) -> Task:
    task = get_task(db, task_id)
    if task.is_template:
        raise ValidationFailed("a recurring template cannot be completed; complete an occurrence instead")
    if task.status == TaskStatus.completed:
        return task
    before = task.status
    _apply_status(task, TaskStatus.completed, now)
    audit.record(
        db,
        action="task.completed",
        source=source,
        entity_type="task",
        entity_id=task.id,
        before={"status": before},
        after={"status": task.status, "completed_at": now},
    )
    if commit:
        db.commit()
    return task


def approve_task(db: Session, task_id: uuid.UUID, *, source: ActionSource = ActionSource.user) -> Task:
    task = get_task(db, task_id)
    if not task.pending_approval:
        return task
    task.pending_approval = False
    audit.record(
        db,
        action="task.approved",
        source=source,
        entity_type="task",
        entity_id=task.id,
        before={"pending_approval": True},
        after={"pending_approval": False},
    )
    db.commit()
    return task


def delete_task(
    db: Session, task_id: uuid.UUID, *, source: ActionSource = ActionSource.user, reason: str | None = None
) -> None:
    task = get_task(db, task_id)
    snap = _snapshot(task)
    if task.is_template:
        # Keep finished occurrences (they carry history); open ones are removed with the template.
        for occ in db.scalars(select(Task).where(Task.recurrence_parent_id == task.id)):
            if occ.status in RESOLVED_STATUSES:
                occ.recurrence_parent_id = None
        db.flush()
    audit.record(
        db,
        action="task.deleted",
        source=source,
        entity_type="task",
        entity_id=task.id,
        before=snap,
        reason=reason,
    )
    db.delete(task)
    db.commit()


def capture_inbox(
    db: Session, text: str, now: datetime, *, source: ActionSource = ActionSource.user
) -> list[Task]:
    titles = [_BULLET.sub("", line).strip() for line in text.splitlines()]
    titles = [t[:500] for t in titles if t]
    if not titles:
        raise ValidationFailed("no tasks found in text")
    created = [
        create_task(db, TaskCreate(title=title, status=TaskStatus.inbox), now, source=source, commit=False)
        for title in titles
    ]
    db.commit()
    return created


def mark_in_progress(db: Session, task: Task, *, source: ActionSource) -> None:
    """Called when work starts on a task; does not commit."""
    if task.status in (TaskStatus.inbox, TaskStatus.planned, TaskStatus.blocked):
        before = task.status
        task.status = TaskStatus.in_progress
        audit.record(
            db,
            action="task.started",
            source=source,
            entity_type="task",
            entity_id=task.id,
            before={"status": before},
            after={"status": task.status},
        )


# ---------------------------------------------------------------- read models


def unresolved_strict_prerequisites(
    db: Session, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_id)
        .join(Task, Task.id == TaskDependency.depends_on_id)
        .where(
            TaskDependency.task_id.in_(task_ids),
            TaskDependency.strict.is_(True),
            Task.status.not_in(RESOLVED_STATUSES),
        )
    )
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for task_id, dep_id in rows:
        out[task_id].append(dep_id)
    return out


def actual_minutes_by_task(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(FocusSession.task_id, func.sum(FocusSession.active_duration_s))
        .where(
            FocusSession.task_id.in_(task_ids),
            FocusSession.type == SessionType.work,
            FocusSession.state == SessionState.finished,
            FocusSession.voided_at.is_(None),
        )
        .group_by(FocusSession.task_id)
    )
    return {task_id: round((secs or 0) / 60, 1) for task_id, secs in rows}


def to_out(db: Session, tasks: list[Task]) -> list[TaskOut]:
    ids = [t.id for t in tasks]
    blocked = unresolved_strict_prerequisites(db, ids)
    actual = actual_minutes_by_task(db, ids)
    return [
        TaskOut.model_validate(t).model_copy(
            update={"blocked_by": blocked.get(t.id, []), "actual_minutes": actual.get(t.id, 0.0)}
        )
        for t in tasks
    ]


def is_open(task: Task) -> bool:
    return task.status in OPEN_TASK_STATUSES


def ensure_workable(db: Session, task: Task) -> None:
    """Rules for starting work on a task (focus timer, scheduler)."""
    if task.is_template:
        raise ValidationFailed("cannot track time on a recurring template; use one of its occurrences")
    if task.status in RESOLVED_STATUSES:
        raise ConflictError(f"task is {task.status.value}; reopen it before working on it")
    if task.pending_approval:
        raise ConflictError("task is an AI proposal awaiting approval")
    blockers = unresolved_strict_prerequisites(db, [task.id]).get(task.id)
    if blockers:
        raise ConflictError(
            "task is blocked by unfinished strict dependencies",
            details={"blocked_by": [str(b) for b in blockers]},
        )
