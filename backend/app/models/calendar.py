import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models.base import Timestamps, UUIDPk, enum_type, utcnow
from app.models.enums import CalendarAccountStatus, CalendarEventStatus, CalendarProvider, EventOrigin


class CalendarAccount(UUIDPk, Timestamps, Base):
    """A connection to a calendar provider. Secrets are stored encrypted (see ``app.crypto``)."""

    __tablename__ = "calendar_accounts"

    provider: Mapped[CalendarProvider] = mapped_column(enum_type(CalendarProvider, "calendar_provider"))
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[CalendarAccountStatus] = mapped_column(
        enum_type(CalendarAccountStatus, "calendar_account_status"), default=CalendarAccountStatus.connected
    )
    # iCal feeds: the secret link works like a password, so it is encrypted at rest and never returned
    # by the API. The hash detects the same link being added twice; the host is shown to the user.
    feed_url_encrypted: Mapped[str | None] = mapped_column(Text)
    feed_url_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    feed_host: Mapped[str | None] = mapped_column(String(255))

    calendars: Mapped[list["Calendar"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Calendar.summary",
    )


class Calendar(UUIDPk, Timestamps, Base):
    __tablename__ = "calendars"
    __table_args__ = (UniqueConstraint("account_id", "provider_calendar_id"),)

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calendar_accounts.id", ondelete="CASCADE"), index=True
    )
    provider_calendar_id: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str | None] = mapped_column(String(64))
    color: Mapped[str | None] = mapped_column(String(20))
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    # All-day events (holidays, birthdays) block time only when this is set.
    all_day_busy: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_token: Mapped[str | None] = mapped_column(String(500))  # iCal: the feed's HTTP ETag
    http_last_modified: Mapped[str | None] = mapped_column(String(100))
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(1000))

    account: Mapped[CalendarAccount] = relationship(back_populates="calendars")


class CalendarEvent(UUIDPk, Timestamps, Base):
    """Local cache of provider events. Recurring events are stored as expanded instances."""

    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("calendar_id", "provider_event_id"),)

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calendars.id", ondelete="CASCADE"), index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String(1000))
    recurring_event_id: Mapped[str | None] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(500))
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    busy: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[CalendarEventStatus] = mapped_column(
        enum_type(CalendarEventStatus, "calendar_event_status"), default=CalendarEventStatus.confirmed
    )
    origin: Mapped[EventOrigin] = mapped_column(
        enum_type(EventOrigin, "event_origin"), default=EventOrigin.user_created
    )
    etag: Mapped[str] = mapped_column(String(64))
    remote_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)  # timezone, transparency, declined; no descriptions
