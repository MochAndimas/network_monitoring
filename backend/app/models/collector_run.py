"""Collector execution telemetry, separate from device metric history."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..core.time import now


class CollectorRun(Base):
    __tablename__ = "collector_runs"
    __table_args__ = (Index("ix_collector_runs_name_checked", "collector_name", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    collector_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    metric_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
