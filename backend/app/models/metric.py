from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        Index("ix_metrics_history_lookup", "device_id", "metric_name", "checked_at"),
        Index("ix_metrics_checked_at", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    device: Mapped["Device"] = relationship(back_populates="metrics")
