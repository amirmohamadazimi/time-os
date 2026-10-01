import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ProjectStatus
from app.schemas.common import ORMModel

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    color: str | None = Field(None, pattern=HEX_COLOR)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    color: str | None = Field(None, pattern=HEX_COLOR)
    status: ProjectStatus | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    color: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class ProjectStats(BaseModel):
    project_id: uuid.UUID
    total_focus_minutes: float
    session_count: int
    tasks_completed: int
    tasks_remaining: int
    estimated_remaining_minutes: int
    last_worked_at: datetime | None
