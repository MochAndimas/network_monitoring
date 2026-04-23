"""Provide SQLAlchemy ORM models for the network monitoring project."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class LatestMetric(Base):
    __tablename__ = "latest_metrics"
    __table_args__ = (
        UniqueConstraint("device_id", "metric_name", name="uq_latest_metrics_device_metric"),
        Index("ix_latest_metrics_device_checked", "device_id", "checked_at"),
        Index("ix_latest_metrics_metric_checked", "metric_name", "checked_at"),
        Index("ix_latest_metrics_status_checked", "status", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("metrics.id"), nullable=False, unique=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # Tracks when the current consecutive "up/ok" streak started.
    uptime_streak_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
