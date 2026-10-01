import uuid
from datetime import date

from fastapi import APIRouter, Query, status

from app.api.deps import DB, Now, Settings
from app.models.enums import SessionSource, SessionType
from app.schemas.common import Page
from app.schemas.focus import FocusSessionOut, ManualSessionCreate, SessionAnnotate
from app.services import sessions

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=Page[FocusSessionOut])
def list_sessions(
    db: DB,
    settings: Settings,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    type: SessionType | None = None,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = Query(None, max_length=200),
    source: SessionSource | None = None,
    include_excluded: bool = True,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items, total = sessions.list_sessions(
        db, settings, date_from=date_from, date_to=date_to, type_=type, task_id=task_id,
        project_id=project_id, tag=tag, q=q, source=source, include_excluded=include_excluded,
        limit=limit, offset=offset,
    )
    return {"items": items, "total": total}


@router.post("", response_model=FocusSessionOut, status_code=status.HTTP_201_CREATED)
def log_session(db: DB, now: Now, settings: Settings, body: ManualSessionCreate):
    return sessions.create_manual(db, body, now, settings)


@router.get("/{session_id}", response_model=FocusSessionOut)
def get_session(db: DB, session_id: uuid.UUID):
    return sessions.get_session(db, session_id)


@router.patch("/{session_id}", response_model=FocusSessionOut)
def annotate_session(db: DB, session_id: uuid.UUID, body: SessionAnnotate):
    return sessions.annotate(db, session_id, body)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def void_session(db: DB, now: Now, session_id: uuid.UUID):
    sessions.void(db, session_id, now)
