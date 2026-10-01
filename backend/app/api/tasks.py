import uuid
from datetime import date

from fastapi import APIRouter, Query, status
from pydantic import AwareDatetime

from app.api.deps import DB, Now, Settings
from app.models.enums import TaskStatus
from app.schemas.focus import FocusSessionOut
from app.schemas.task import InboxCapture, RecurrenceWindow, TaskCreate, TaskOut, TaskUpdate
from app.services import recurrence, sessions, tasks

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    db: DB,
    status: list[TaskStatus] | None = Query(None),
    project_id: uuid.UUID | None = None,
    category: str | None = None,
    tag: str | None = None,
    q: str | None = Query(None, max_length=200),
    planned_date: date | None = None,
    due_before: AwareDatetime | None = None,
    pending_approval: bool | None = None,
    include_templates: bool = False,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    rows = tasks.list_tasks(
        db, statuses=status, project_id=project_id, category=category, tag=tag, q=q,
        planned_date=planned_date, due_before=due_before, pending_approval=pending_approval,
        include_templates=include_templates, limit=limit, offset=offset,
    )
    return tasks.to_out(db, rows)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(db: DB, now: Now, body: TaskCreate):
    return tasks.to_out(db, [tasks.create_task(db, body, now)])[0]


@router.post("/inbox", response_model=list[TaskOut], status_code=status.HTTP_201_CREATED)
def capture_inbox(db: DB, now: Now, body: InboxCapture):
    return tasks.to_out(db, tasks.capture_inbox(db, body.text, now))


@router.get("/categories", response_model=list[str])
def list_categories(db: DB):
    return tasks.categories(db)


@router.post("/recurrences/generate", response_model=list[TaskOut])
def generate_occurrences(db: DB, settings: Settings, body: RecurrenceWindow):
    created = recurrence.generate_occurrences(db, body.start_date, body.end_date, settings)
    return tasks.to_out(db, created)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(db: DB, task_id: uuid.UUID):
    return tasks.to_out(db, [tasks.get_task(db, task_id)])[0]


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(db: DB, now: Now, task_id: uuid.UUID, body: TaskUpdate):
    return tasks.to_out(db, [tasks.update_task(db, task_id, body, now)])[0]


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(db: DB, task_id: uuid.UUID):
    tasks.delete_task(db, task_id)


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(db: DB, now: Now, task_id: uuid.UUID):
    return tasks.to_out(db, [tasks.complete_task(db, task_id, now)])[0]


@router.post("/{task_id}/approve", response_model=TaskOut)
def approve_task(db: DB, task_id: uuid.UUID):
    return tasks.to_out(db, [tasks.approve_task(db, task_id)])[0]


@router.get("/{task_id}/sessions", response_model=list[FocusSessionOut])
def task_sessions(db: DB, settings: Settings, task_id: uuid.UUID):
    tasks.get_task(db, task_id)
    rows, _ = sessions.list_sessions(db, settings, task_id=task_id, limit=1000)
    return rows
