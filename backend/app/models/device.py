"""Provide SQLAlchemy ORM models for the network monitoring project."""

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base


class Device(Base):
    """Represent device behavior and data for SQLAlchemy ORM models.

    Inherits from `Base` to match the surrounding framework or persistence model.
    """
    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_active_type_name", "is_active", "device_type", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    metrics: Mapped[list["Metric"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="device")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="device")
