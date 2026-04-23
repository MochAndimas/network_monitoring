"""Provide SQLAlchemy ORM models for the network monitoring project."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.time import now
from ..db.base import Base

class MetricDailyRollup(Base):
    __tablename__ = "metric_daily_rollups"
    __table_args__ = (UniqueConstraint("device_id", "rollup_date", name="uq_metric_daily_rollups_device_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    rollup_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ping_samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    down_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uptime_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_packet_loss_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_jitter_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_jitter_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    device: Mapped["Device"] = relationship()
