import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models.base import Timestamps, UUIDPk, enum_type
from app.models.enums import Energy, Priority, TaskSource, TaskStatus, TimeOfDay
from app.models.project import Project


class Task(UUIDPk, Timestamps, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("estimated_minutes IS NULL OR estimated_minutes > 0", name="estimate_positive"),
        CheckConstraint("importance IS NULL OR importance BETWEEN 1 AND 5", name="importance_range"),
        CheckConstraint("urgency IS NULL OR urgency BETWEEN 1 AND 5", name="urgency_range"),
        UniqueConstraint("recurrence_parent_id", "occurrence_date", name="uq_tasks_occurrence"),
    )

    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    priority: Mapped[Priority] = mapped_column(enum_type(Priority, "task_priority"), default=Priority.medium)
    status: Mapped[TaskStatus] = mapped_column(
        enum_type(TaskStatus, "task_status"), default=TaskStatus.inbox, index=True
    )
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    earliest_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    planned_date: Mapped[date | None] = mapped_column(Date, index=True)
    preferred_time: Mapped[TimeOfDay | None] = mapped_column(enum_type(TimeOfDay, "task_preferred_time"))
    energy_requirement: Mapped[Energy | None] = mapped_column(enum_type(Energy, "task_energy"))
    importance: Mapped[int | None] = mapped_column(SmallInteger)
    urgency: Mapped[int | None] = mapped_column(SmallInteger)
    recurrence_rule: Mapped[str | None] = mapped_column(String(500))
    recurrence_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[TaskSource] = mapped_column(enum_type(TaskSource, "task_source"), default=TaskSource.user)
    pending_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    project: Mapped[Project | None] = relationship(lazy="joined")
    dependencies: Mapped[list["TaskDependency"]] = relationship(
        foreign_keys="TaskDependency.task_id",
        cascade="all, delete-orphan",
        lazy="selectin",
        passive_deletes=True,
    )

    @property
    def is_template(self) -> bool:
        return self.recurrence_rule is not None


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (CheckConstraint("task_id <> depends_on_id", name="not_self"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    strict: Mapped[bool] = mapped_column(Boolean, default=True)
