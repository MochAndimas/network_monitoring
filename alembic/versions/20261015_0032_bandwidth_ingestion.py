"""Durable flow spool checkpoints and classified observations.

Revision ID: 20261015_0032
Revises: 20261015_0031
"""

import sqlalchemy as sa

from alembic import op

revision = "20261015_0032"
down_revision = "20261015_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bandwidth_flow_streams",
        sa.Column("stream_id", sa.String(36), primary_key=True),
        sa.Column("router_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("heartbeat_ns", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
    )
    op.create_table(
        "bandwidth_flow_segments",
        sa.Column("stream_id", sa.String(36), sa.ForeignKey("bandwidth_flow_streams.stream_id"), primary_key=True),
        sa.Column("segment_id", sa.String(32), primary_key=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("offset_bytes", sa.BigInteger(), nullable=False),
        sa.Column("accepted_count", sa.BigInteger(), nullable=False),
        sa.Column("rejected_count", sa.BigInteger(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.CheckConstraint("offset_bytes >= 0 AND offset_bytes <= size_bytes", name="ck_bw_segment_offset"),
    )
    op.create_index("ix_bw_segment_pending", "bandwidth_flow_segments", ["stream_id", "completed"])
    op.create_table(
        "bandwidth_flow_rejections",
        sa.Column("stream_id", sa.String(36), sa.ForeignKey("bandwidth_flow_streams.stream_id"), primary_key=True),
        sa.Column("reason", sa.String(64), primary_key=True),
        sa.Column("record_count", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "bandwidth_flows",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("stream_id", sa.String(36), nullable=False),
        sa.Column("segment_id", sa.String(32), nullable=False),
        sa.Column("record_offset", sa.BigInteger(), nullable=False),
        sa.Column("router_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("bandwidth_clients.id")),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("device_ip", sa.String(15), nullable=False),
        sa.Column("remote_ip", sa.String(15), nullable=False),
        sa.Column("source_ip", sa.String(15), nullable=False),
        sa.Column("destination_ip", sa.String(15), nullable=False),
        sa.Column("post_nat_source", sa.String(15)),
        sa.Column("post_nat_destination", sa.String(15)),
        sa.Column("input_interface", sa.BigInteger(), nullable=False),
        sa.Column("output_interface", sa.BigInteger(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("packets", sa.BigInteger(), nullable=False),
        sa.Column("started_ns", sa.BigInteger(), nullable=False),
        sa.Column("ended_ns", sa.BigInteger(), nullable=False),
        sa.Column("received_ns", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["stream_id", "segment_id"],
            ["bandwidth_flow_segments.stream_id", "bandwidth_flow_segments.segment_id"],
            name="fk_bw_flow_segment",
        ),
        sa.UniqueConstraint("stream_id", "segment_id", "record_offset", name="uq_bw_flow_position"),
        sa.CheckConstraint("byte_count > 0 AND packets >= 0", name="ck_bw_flow_counters"),
        sa.CheckConstraint("started_ns > 0 AND ended_ns >= started_ns", name="ck_bw_flow_time"),
        sa.CheckConstraint("direction IN ('upload', 'download')", name="ck_bw_flow_direction"),
    )
    op.create_index("ix_bw_flow_device_time", "bandwidth_flows", ["router_id", "device_ip", "started_ns"])
    op.create_index("ix_bw_flow_client_time", "bandwidth_flows", ["router_id", "client_id", "started_ns"])


def downgrade() -> None:
    for table in ("bandwidth_flows", "bandwidth_flow_rejections", "bandwidth_flow_segments", "bandwidth_flow_streams"):
        if op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("Export and retire populated flow data and replay checkpoints before downgrading")
    # MySQL may reuse a covering router index to enforce its FK. Drop the table
    # with its indexes atomically instead of removing an FK-supporting index.
    op.drop_table("bandwidth_flows")
    op.drop_table("bandwidth_flow_rejections")
    op.drop_index("ix_bw_segment_pending", table_name="bandwidth_flow_segments")
    op.drop_table("bandwidth_flow_segments")
    op.drop_table("bandwidth_flow_streams")
