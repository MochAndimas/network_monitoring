"""Transaction-scoped producer coordination for each delivery stream."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base


class NotificationOutboxStream(Base):
    __tablename__ = "notification_outbox_streams"

    channel: Mapped[str] = mapped_column(String(30), primary_key=True)
    stream_key: Mapped[str] = mapped_column(String(128), primary_key=True)
