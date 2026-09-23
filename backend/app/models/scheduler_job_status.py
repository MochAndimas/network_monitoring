"""SQLAlchemy model definitions for scheduler job status records."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..core.time import now
from ..db.base import Base


class SchedulerJobStatus(Base):
    """SQLAlchemy ORM model for SchedulerJobStatus records."""

    __tablename__ = "scheduler_job_statuses"
    __table_args__ = (Index("uq_scheduler_job_owner", "job_name", "agent_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, default="central", server_default="central")
    agent_site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
