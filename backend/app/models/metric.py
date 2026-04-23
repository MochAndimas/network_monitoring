"""Provide SQLAlchemy ORM models for the network monitoring project."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..core.time import now


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        Index("ix_metrics_history_lookup", "device_id", "metric_name", "checked_at"),
        Index("ix_metrics_history_lookup_with_id", "device_id", "metric_name", "checked_at", "id"),
        Index("ix_metrics_checked_at", "checked_at"),
        Index("ix_metrics_name_device_checked", "metric_name", "device_id", "checked_at"),
        Index("ix_metrics_history_status_checked", "status", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    device: Mapped["Device"] = relationship(back_populates="metrics")
