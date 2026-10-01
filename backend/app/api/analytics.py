import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.analytics import service
from app.analytics.frame import Filters
from app.api.deps import DB, Settings
from app.models.enums import SessionType
from app.schemas import analytics as s

router = APIRouter(prefix="/analytics", tags=["analytics"])


def filters(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    type: SessionType = SessionType.work,
    project_id: uuid.UUID | None = None,
    tag: str | None = None,
) -> Filters:
    return Filters(date_from=date_from, date_to=date_to, type=type, project_id=project_id, tag=tag)


F = Annotated[Filters, Depends(filters)]
OPTS = {"response_model_by_alias": True}


@router.get("/summary", response_model=s.Summary, **OPTS)
def summary(db: DB, settings: Settings, f: F):
    return service.summary(db, settings, f)


@router.get("/timeseries", response_model=s.Timeseries, **OPTS)
def timeseries(db: DB, settings: Settings, f: F, granularity: Literal["day", "week", "month"] = "day"):
    return service.timeseries(db, settings, f, granularity)


@router.get("/by-hour", response_model=s.ByHour, **OPTS)
def by_hour(db: DB, settings: Settings, f: F):
    return service.by_hour(db, settings, f)


@router.get("/by-weekday", response_model=s.ByWeekday, **OPTS)
def by_weekday(db: DB, settings: Settings, f: F):
    return service.by_weekday(db, settings, f)


@router.get("/by-project", response_model=s.ByProject, **OPTS)
def by_project(db: DB, settings: Settings, f: F):
    return service.by_project(db, settings, f)


@router.get("/by-tag", response_model=s.ByTag, **OPTS)
def by_tag(db: DB, settings: Settings, f: F):
    return service.by_tag(db, settings, f)


@router.get("/gaps", response_model=s.Gaps, **OPTS)
def gaps(db: DB, settings: Settings, f: F):
    return service.gaps(db, settings, f)


@router.get("/estimation", response_model=s.Estimation)
def estimation(db: DB, settings: Settings, group_by: Literal["category", "project"] = "category"):
    return service.estimation_accuracy(db, settings, group_by)


@router.get("/patterns", response_model=s.Patterns, **OPTS)
def patterns(db: DB, settings: Settings, f: F):
    return service.find_patterns(db, settings, f)
