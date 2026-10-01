from datetime import datetime

from sqlalchemy import JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime
from app.models.base import utcnow


class AppSettings(Base):
    """Single row (id=1) holding the JSON document validated by ``UserSettings``."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
