"""Load finished sessions into a pandas DataFrame with local-time columns.

Local time for a session is ``start_time + tz_offset_minutes`` (the offset recorded when the
session happened), so hour/weekday statistics stay correct across travel and DST.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FocusSession
from app.models.enums import SessionState, SessionType
from app.schemas.settings import UserSettings
from app.timeutil import day_bounds_utc

COLUMNS = [
    "id", "task_id", "project_id", "category", "type", "source", "start", "end", "local_start",
    "local_end", "local_date", "hour", "weekday", "active_s", "paused_s", "elapsed_s", "pause_count",
    "end_reason", "outcome", "tags",
]  # fmt: skip


@dataclass(frozen=True)
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    type: SessionType | None = SessionType.work
    project_id: uuid.UUID | None = None
    tag: str | None = None


@dataclass
class SessionFrame:
    df: pd.DataFrame
    excluded_count: int
    filters: Filters


def load(db: Session, settings: UserSettings, filters: Filters) -> SessionFrame:
    stmt = select(FocusSession).where(
        FocusSession.state == SessionState.finished, FocusSession.voided_at.is_(None)
    )
    # Pad the UTC window by a day each side; the exact local-date filter is applied below.
    if filters.date_from:
        stmt = stmt.where(
            FocusSession.start_time >= day_bounds_utc(filters.date_from, settings.tz)[0] - timedelta(days=1)
        )
    if filters.date_to:
        stmt = stmt.where(
            FocusSession.start_time < day_bounds_utc(filters.date_to, settings.tz)[1] + timedelta(days=1)
        )
    if filters.type:
        stmt = stmt.where(FocusSession.type == filters.type)
    if filters.project_id:
        stmt = stmt.where(FocusSession.project_id == filters.project_id)
    records, excluded = [], 0
    wanted_tag = filters.tag.lower() if filters.tag else None
    for s in db.scalars(stmt).unique():
        offset = timedelta(minutes=s.tz_offset_minutes)
        local_start = (s.start_time + offset).replace(tzinfo=None)
        local_date = local_start.date()
        if filters.date_from and local_date < filters.date_from:
            continue
        if filters.date_to and local_date > filters.date_to:
            continue
        if wanted_tag and not any(t.lower() == wanted_tag for t in s.tags or []):
            continue
        if s.exclude_from_stats:
            excluded += 1
            continue
        records.append({
            "id": s.id, "task_id": s.task_id, "project_id": s.project_id, "category": s.category_snapshot,
            "type": s.type.value, "source": s.source.value, "start": s.start_time, "end": s.end_time,
            "local_start": local_start, "local_end": (s.end_time + offset).replace(tzinfo=None),
            "local_date": local_date, "hour": local_start.hour, "weekday": local_start.weekday(),
            "active_s": s.active_duration_s or 0, "paused_s": s.paused_duration_s or 0,
            "elapsed_s": s.elapsed_s or 0, "pause_count": s.pause_count,
            "end_reason": s.end_reason.value if s.end_reason else "unknown",
            "outcome": s.outcome.value if s.outcome else None, "tags": list(s.tags or []),
        })  # fmt: skip
    df = pd.DataFrame.from_records(records, columns=COLUMNS)
    if not df.empty:
        df = df.sort_values("start").reset_index(drop=True)
    return SessionFrame(df=df, excluded_count=excluded, filters=filters)
