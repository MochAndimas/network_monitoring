"""SQLAlchemy model definitions for incident records."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..core.time import now

if TYPE_CHECKING:
    from .device import Device


class Incident(Base):
    """SQLAlchemy ORM model for Incident records."""
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_status_started_at", "status", "started_at"),
        Index("ix_incidents_device_status", "device_id", "status"),
        Index("ix_incidents_ack_status_started_at", "status", "acknowledged_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    device: Mapped[Device | None] = relationship(back_populates="incidents")
    timeline_events: Mapped[list["IncidentTimelineEvent"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentTimelineEvent.created_at",
    )


class IncidentTimelineEvent(Base):
    """Append-only event log for incident workflow and notification history."""

    __tablename__ = "incident_timeline_events"
    __table_args__ = (
        Index("ix_incident_timeline_incident_created", "incident_id", "created_at"),
        Index("ix_incident_timeline_event_type_created", "event_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    event_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="timeline_events")
