"""Define module logic for `backend/app/models/metric_cold_archive.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.time import now
from ..db.base import Base

if TYPE_CHECKING:
    from .device import Device


class MetricColdArchive(Base):
    """Perform MetricColdArchive.

    This class encapsulates related behavior and data for this domain area.
    """
    __tablename__ = "metric_cold_archives"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "archive_date",
            "metric_name",
            "status",
            "unit",
            name="uq_metric_cold_archives_device_date_metric_status_unit",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    archive_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    archive_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    numeric_sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_metric_value: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    device: Mapped[Device] = relationship()
