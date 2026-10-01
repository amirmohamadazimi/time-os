from fastapi import APIRouter, status

from app.api.deps import DB, Now, Settings
from app.models import FocusSession
from app.schemas.focus import FocusAnnotate, FocusFinish, FocusSessionOut, FocusStart, FocusSwitch, LiveSessionOut
from app.services import focus

router = APIRouter(prefix="/focus", tags=["focus"])


def _live(session: FocusSession, now) -> LiveSessionOut:
    base = FocusSessionOut.model_validate(session).model_dump()
    return LiveSessionOut(**base, server_time=now, active_so_far_s=focus.active_so_far(session, now))


@router.get("/current", response_model=LiveSessionOut | None)
def current(db: DB, now: Now):
    session = focus.get_live(db)
    return _live(session, now) if session else None


@router.post("/start", response_model=LiveSessionOut, status_code=status.HTTP_201_CREATED)
def start(db: DB, now: Now, settings: Settings, body: FocusStart):
    return _live(focus.start(db, body, now, settings), now)


@router.post("/pause", response_model=LiveSessionOut)
def pause(db: DB, now: Now):
    return _live(focus.pause(db, now), now)


@router.post("/resume", response_model=LiveSessionOut)
def resume(db: DB, now: Now):
    return _live(focus.resume(db, now), now)


@router.patch("/current", response_model=LiveSessionOut)
def annotate(db: DB, now: Now, body: FocusAnnotate):
    return _live(focus.annotate(db, body), now)


@router.post("/finish", response_model=FocusSessionOut)
def finish(db: DB, now: Now, body: FocusFinish):
    return focus.finish(db, body, now)


@router.post("/switch", response_model=LiveSessionOut)
def switch(db: DB, now: Now, settings: Settings, body: FocusSwitch):
    return _live(focus.switch(db, body, now, settings), now)


@router.delete("/current", status_code=status.HTTP_204_NO_CONTENT)
def discard(db: DB, now: Now):
    focus.discard(db, now)
