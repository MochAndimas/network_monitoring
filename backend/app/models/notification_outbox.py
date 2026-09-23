"""Durable notification jobs; delivery state is separate from alert state."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import DATETIME

from ..core.time import utcnow
from ..db.base import Base


OUTBOX_TIMESTAMP = DateTime().with_variant(DATETIME(fsp=6), "mysql")


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("uq_notification_outbox_key", "idempotency_key", unique=True),
        Index("ix_notification_outbox_due", "channel", "status", "available_at", "id"),
        Index("ix_notification_outbox_lease", "channel", "status", "lease_until", "id"),
        Index("ix_notification_outbox_stream", "channel", "stream_key", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stream_key: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(OUTBOX_TIMESTAMP, nullable=False, default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(OUTBOX_TIMESTAMP, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(OUTBOX_TIMESTAMP, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(OUTBOX_TIMESTAMP, nullable=False, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(OUTBOX_TIMESTAMP, nullable=True)
