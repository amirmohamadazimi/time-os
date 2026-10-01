"""Estimated vs actual duration, and the historical multipliers the scheduler uses.

For each completed task with an estimate and logged focus time, ``ratio = actual / estimate``.
Per group (category or project):

* ``ratio``        = sum(actual) / sum(estimate)   (the headline "Estimated 60 → Actual 87")
* ``median_ratio`` = median of per-task ratios     (robust to one runaway task)
* ``multiplier``   = exp(w · median(log ratio)), w = 0 if n < min_samples else n / (n + prior_strength),
                     clamped to [min_multiplier, max_multiplier]. Few samples ⇒ stays near 1.0.
"""

import math
import statistics
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FocusSession, Project, Task
from app.models.enums import SessionState, SessionType, TaskStatus
from app.schemas.settings import Personalization

UNCATEGORISED = "(uncategorised)"
NO_PROJECT = "(no project)"


@dataclass(frozen=True)
class Observation:
    task_id: uuid.UUID
    title: str
    category: str | None
    project_id: uuid.UUID | None
    project_name: str | None
    estimate_minutes: float
    actual_minutes: float

    @property
    def ratio(self) -> float:
        return self.actual_minutes / self.estimate_minutes


def observations(db: Session) -> list[Observation]:
    actual = (
        select(FocusSession.task_id, func.sum(FocusSession.active_duration_s).label("secs"))
        .where(
            FocusSession.type == SessionType.work,
            FocusSession.state == SessionState.finished,
            FocusSession.voided_at.is_(None),
            FocusSession.task_id.is_not(None),
        )
        .group_by(FocusSession.task_id)
        .subquery()
    )
    rows = db.execute(
        select(Task.id, Task.title, Task.category, Task.project_id, Project.name, Task.estimated_minutes,
               actual.c.secs)
        .join(actual, actual.c.task_id == Task.id)
        .outerjoin(Project, Project.id == Task.project_id)
        .where(Task.status == TaskStatus.completed, Task.estimated_minutes.is_not(None), actual.c.secs > 0)
    )  # fmt: skip
    return [Observation(r[0], r[1], r[2], r[3], r[4], float(r[5]), r[6] / 60) for r in rows]


def shrunk_multiplier(log_ratios: list[float], p: Personalization) -> tuple[float, float]:
    """(multiplier, weight) for a group's per-task log ratios."""
    n = len(log_ratios)
    if n < p.min_samples:
        return 1.0, 0.0
    weight = n / (n + p.prior_strength)
    value = math.exp(weight * statistics.median(log_ratios))
    return round(min(max(value, p.min_multiplier), p.max_multiplier), 2), round(weight, 2)


def confidence(n: int, p: Personalization) -> str:
    if n < p.min_samples:
        return "insufficient"
    return "strong" if n >= p.strong_samples else "moderate"


def group(obs: list[Observation], group_by: str, p: Personalization) -> list[dict]:
    groups: dict[tuple, list[Observation]] = {}
    for o in obs:
        key = (
            (o.category or UNCATEGORISED, None)
            if group_by == "category"
            else (o.project_name or NO_PROJECT, o.project_id)
        )
        groups.setdefault(key, []).append(o)
    rows = []
    for (label, key_id), items in groups.items():
        est = sum(o.estimate_minutes for o in items)
        act = sum(o.actual_minutes for o in items)
        multiplier, weight = shrunk_multiplier([math.log(o.ratio) for o in items], p)
        tendency = "underestimate" if act > est * 1.1 else "overestimate" if act < est * 0.9 else "accurate"
        rows.append({
            "group": label,
            "group_id": key_id,
            "samples": len(items),
            "avg_estimate_minutes": round(est / len(items), 1),
            "avg_actual_minutes": round(act / len(items), 1),
            "ratio": round(act / est, 2),
            "median_ratio": round(statistics.median(o.ratio for o in items), 2),
            "multiplier": multiplier,
            "weight": weight,
            "confidence": confidence(len(items), p),
            "tendency": tendency,
        })  # fmt: skip
    return sorted(rows, key=lambda r: r["samples"], reverse=True)


@dataclass(frozen=True)
class EstimationModel:
    """Lookup used by the scheduler: category, then project, then global multiplier."""

    by_category: dict[str, float]
    by_project: dict[uuid.UUID, float]
    overall: float

    def multiplier(self, category: str | None, project_id: uuid.UUID | None) -> float:
        if category and category in self.by_category:
            return self.by_category[category]
        if project_id and project_id in self.by_project:
            return self.by_project[project_id]
        return self.overall

    def effective_estimate(self, minutes: int, category: str | None, project_id: uuid.UUID | None) -> int:
        return int(round(minutes * self.multiplier(category, project_id)))


def build_model(obs: list[Observation], p: Personalization) -> EstimationModel:
    def table(key) -> dict:
        buckets: dict = {}
        for o in obs:
            k = key(o)
            if k is not None:
                buckets.setdefault(k, []).append(math.log(o.ratio))
        return {k: shrunk_multiplier(v, p)[0] for k, v in buckets.items() if len(v) >= p.min_samples}

    overall = shrunk_multiplier([math.log(o.ratio) for o in obs], p)[0] if obs else 1.0
    return EstimationModel(table(lambda o: o.category), table(lambda o: o.project_id), overall)
