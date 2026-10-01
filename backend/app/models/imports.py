import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime
from app.models.base import UUIDPk, enum_type, utcnow
from app.models.enums import ImportRecordStatus


class ImportBatch(UUIDPk, Base):
    __tablename__ = "import_batches"

    kind: Mapped[str] = mapped_column(String(50), default="focus_sessions")
    filename: Mapped[str] = mapped_column(String(500))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    rolled_back_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ImportRecord(Base):
    """Every input row, preserved verbatim, with its validation result."""

    __tablename__ = "import_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON)
    status: Mapped[ImportRecordStatus] = mapped_column(enum_type(ImportRecordStatus, "import_record_status"))
    errors: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("focus_sessions.id", ondelete="SET NULL")
    )
