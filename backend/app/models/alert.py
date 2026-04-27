"""Define module logic for `backend/app/models/alert.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..core.time import now

if TYPE_CHECKING:
    from .device import Device


class Alert(Base):
    """Perform Alert.

    This class encapsulates related behavior and data for this domain area.
    """
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_status_created_at", "status", "created_at"),
        Index("ix_alerts_device_status_type", "device_id", "status", "alert_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device: Mapped[Device | None] = relationship(back_populates="alerts")
