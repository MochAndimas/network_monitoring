"""SQLAlchemy model for materialized site/device-type daily summaries."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.time import now
from ..db.base import Base


class MetricSiteTypeDailySummary(Base):
    """Materialized daily metric summary grouped by site and device type."""

    __tablename__ = "metric_site_type_daily_summaries"
    __table_args__ = (
        UniqueConstraint("summary_date", "site", "device_type", name="uq_metric_site_type_daily_summary"),
        Index("ix_metric_site_type_summary_date_site_type", "summary_date", "site", "device_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    site: Mapped[str] = mapped_column(String(100), nullable=False, default="Unassigned")
    device_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    device_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ping_samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    down_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_uptime_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_packet_loss_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_jitter_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_jitter_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
