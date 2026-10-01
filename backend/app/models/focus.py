import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models.base import Timestamps, UUIDPk, enum_type
from app.models.enums import EndReason, Outcome, SessionSource, SessionState, SessionType
from app.models.project import Project
from app.models.task import Task


class FocusSession(UUIDPk, Timestamps, Base):
    """One block of actual work or rest. Finished sessions are immutable history:
    times and durations never change; only annotations may be edited (and are audited)."""

    __tablename__ = "focus_sessions"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_focus_sessions_external"),)

    task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[SessionType] = mapped_column(
        enum_type(SessionType, "session_type"), default=SessionType.work
    )
    state: Mapped[SessionState] = mapped_column(enum_type(SessionState, "session_state"), index=True)
    source: Mapped[SessionSource] = mapped_column(enum_type(SessionSource, "session_source"))

    start_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    tz_offset_minutes: Mapped[int] = mapped_column(Integer, default=0)
    planned_duration_s: Mapped[int | None] = mapped_column(Integer)
    active_duration_s: Mapped[int | None] = mapped_column(Integer)
    paused_duration_s: Mapped[int] = mapped_column(Integer, default=0)
    paused_since: Mapped[datetime | None] = mapped_column(UTCDateTime)
    pause_count: Mapped[int | None] = mapped_column(Integer)

    end_reason: Mapped[EndReason | None] = mapped_column(enum_type(EndReason, "session_end_reason"))
    outcome: Mapped[Outcome | None] = mapped_column(enum_type(Outcome, "session_outcome"))
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Snapshots taken at session start, so later task edits don't rewrite history.
    task_title_snapshot: Mapped[str | None] = mapped_column(String(500))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    category_snapshot: Mapped[str | None] = mapped_column(String(100))

    external_id: Mapped[str | None] = mapped_column(String(200))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("import_batches.id", ondelete="SET NULL"), index=True
    )
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclude_from_stats: Mapped[bool] = mapped_column(Boolean, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    task: Mapped[Task | None] = relationship(lazy="joined")
    project: Mapped[Project | None] = relationship(lazy="joined")

    @property
    def elapsed_s(self) -> int | None:
        if self.end_time is None:
            return None
        return int((self.end_time - self.start_time).total_seconds())

    @property
    def completed(self) -> bool:
        return self.end_reason == EndReason.completed

    @property
    def stopped(self) -> bool:
        return self.end_reason == EndReason.stopped
