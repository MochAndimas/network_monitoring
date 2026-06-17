"""SQLAlchemy model definitions for threshold and alert-intelligence records."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..core.time import now


class Threshold(Base):
    """SQLAlchemy ORM model for Threshold records."""
    __tablename__ = "thresholds"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ThresholdOverride(Base):
    """Scoped threshold override by device, device type, or site."""

    __tablename__ = "threshold_overrides"
    __table_args__ = (
        Index("ix_threshold_overrides_key_active", "threshold_key", "is_active"),
        Index("ix_threshold_overrides_device_active", "device_id", "is_active"),
        Index("ix_threshold_overrides_type_active", "device_type", "is_active"),
        Index("ix_threshold_overrides_site_active", "site", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    threshold_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class MaintenanceWindow(Base):
    """Scheduled alert suppression window scoped to a device or site."""

    __tablename__ = "maintenance_windows"
    __table_args__ = (
        Index("ix_maintenance_windows_active_time", "is_active", "starts_at", "ends_at"),
        Index("ix_maintenance_windows_device_active", "device_id", "is_active"),
        Index("ix_maintenance_windows_site_active", "site", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
