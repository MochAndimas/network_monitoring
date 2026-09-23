"""Immutable alert references carried by a queued notification."""

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class NotificationOutboxAlert(Base):
    __tablename__ = "notification_outbox_alerts"
    __table_args__ = (Index("ix_outbox_alert_reference", "alert_id", "action", "outbox_id"),)

    outbox_id: Mapped[int] = mapped_column(ForeignKey("notification_outbox.id", ondelete="CASCADE"), primary_key=True)
    # Deliberately not an Alert FK: retention may remove the domain record.
    # Keep its historical identifier; delivery still has its immutable message.
    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(30), primary_key=True)
