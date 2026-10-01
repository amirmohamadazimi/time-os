from datetime import date

from pydantic import BaseModel

from app.schemas.focus import LiveSessionOut
from app.schemas.task import TaskOut


class TodayDashboard(BaseModel):
    date: date
    timezone: str
    focused_minutes: float
    rest_minutes: float
    planned_minutes: float
    sessions_today: int
    current_session: LiveSessionOut | None
    next_tasks: list[TaskOut]
    due_today: list[TaskOut]
    overdue: list[TaskOut]
    inbox_count: int
    pending_approval_count: int
