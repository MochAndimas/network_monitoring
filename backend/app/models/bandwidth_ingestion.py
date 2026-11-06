"""Durable per-stream progress and append-only classified flow observations."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class BandwidthFlowStream(Base):
    __tablename__ = "bandwidth_flow_streams"

    stream_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    heartbeat_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64))


class BandwidthFlowSegment(Base):
    __tablename__ = "bandwidth_flow_segments"
    __table_args__ = (
        CheckConstraint("offset_bytes >= 0 AND offset_bytes <= size_bytes", name="ck_bw_segment_offset"),
        Index("ix_bw_segment_pending", "stream_id", "completed"),
    )

    stream_id: Mapped[str] = mapped_column(String(36), ForeignKey("bandwidth_flow_streams.stream_id"), primary_key=True)
    segment_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offset_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BandwidthFlowRejection(Base):
    __tablename__ = "bandwidth_flow_rejections"

    stream_id: Mapped[str] = mapped_column(String(36), ForeignKey("bandwidth_flow_streams.stream_id"), primary_key=True)
    reason: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_count: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BandwidthFlow(Base):
    __tablename__ = "bandwidth_flows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["stream_id", "segment_id"],
            ["bandwidth_flow_segments.stream_id", "bandwidth_flow_segments.segment_id"],
            name="fk_bw_flow_segment",
        ),
        UniqueConstraint("stream_id", "segment_id", "record_offset", name="uq_bw_flow_position"),
        Index("ix_bw_flow_device_time", "router_id", "device_ip", "started_ns"),
        Index("ix_bw_flow_client_time", "router_id", "client_id", "started_ns"),
        CheckConstraint("byte_count > 0 AND packets >= 0", name="ck_bw_flow_counters"),
        CheckConstraint("started_ns > 0 AND ended_ns >= started_ns", name="ck_bw_flow_time"),
        CheckConstraint("direction IN ('upload', 'download')", name="ck_bw_flow_direction"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(36), nullable=False)
    segment_id: Mapped[str] = mapped_column(String(32), nullable=False)
    record_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    router_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("bandwidth_clients.id"))
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    device_ip: Mapped[str] = mapped_column(String(15), nullable=False)
    remote_ip: Mapped[str] = mapped_column(String(15), nullable=False)
    source_ip: Mapped[str] = mapped_column(String(15), nullable=False)
    destination_ip: Mapped[str] = mapped_column(String(15), nullable=False)
    post_nat_source: Mapped[str | None] = mapped_column(String(15))
    post_nat_destination: Mapped[str | None] = mapped_column(String(15))
    input_interface: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_interface: Mapped[int] = mapped_column(BigInteger, nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    packets: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ended_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
