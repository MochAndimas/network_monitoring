"""SQLAlchemy model definitions for retention bucket progress markers."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.time import now
from ..db.base import Base


class RetentionBucketProgress(Base):
    """Track raw-metric retention buckets that have already been processed."""
    __tablename__ = "retention_bucket_progress"
    __table_args__ = (
        UniqueConstraint(
            "bucket_kind",
            "device_id",
            "bucket_date",
            "metric_name",
            "status",
            "unit",
            name="uq_retention_bucket_progress_bucket",
        ),
        Index("ix_retention_bucket_progress_lookup", "bucket_kind", "bucket_date", "device_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bucket_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    bucket_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    source_metric_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_max_metric_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_latest_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
