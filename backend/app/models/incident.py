"""Define module logic for `backend/app/models/incident.py`.

This module contains project-specific implementation details.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..core.time import now


class Incident(Base):
    """Perform Incident.

    This class encapsulates related behavior and data for this domain area.
    """
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_status_started_at", "status", "started_at"),
        Index("ix_incidents_device_status", "device_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device: Mapped["Device | None"] = relationship(back_populates="incidents")
