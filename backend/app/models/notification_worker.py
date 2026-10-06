"""Persistent process heartbeat, independent of API process memory."""

from datetime import datetime
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .notification_outbox import OUTBOX_TIMESTAMP


class NotificationWorker(Base):
    __tablename__ = "notification_workers"
    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(OUTBOX_TIMESTAMP, nullable=False)
