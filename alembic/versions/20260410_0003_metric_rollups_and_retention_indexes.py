"""metric daily rollups and retention indexes

Revision ID: 20260410_0003
Revises: 20260409_0002
Create Date: 2026-04-10 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260410_0003"
down_revision = "20260409_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_daily_rollups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("rollup_date", sa.Date(), nullable=False),
        sa.Column("total_samples", sa.Integer(), nullable=False),
        sa.Column("ping_samples", sa.Integer(), nullable=False),
        sa.Column("down_count", sa.Integer(), nullable=False),
        sa.Column("uptime_percentage", sa.Float(), nullable=True),
        sa.Column("average_ping_ms", sa.Float(), nullable=True),
        sa.Column("min_ping_ms", sa.Float(), nullable=True),
        sa.Column("max_ping_ms", sa.Float(), nullable=True),
        sa.Column("average_packet_loss_percent", sa.Float(), nullable=True),
        sa.Column("average_jitter_ms", sa.Float(), nullable=True),
        sa.Column("max_jitter_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "rollup_date", name="uq_metric_daily_rollups_device_date"),
    )
    op.create_index(op.f("ix_metric_daily_rollups_id"), "metric_daily_rollups", ["id"], unique=False)
    op.create_index(op.f("ix_metric_daily_rollups_device_id"), "metric_daily_rollups", ["device_id"], unique=False)
    op.create_index(op.f("ix_metric_daily_rollups_rollup_date"), "metric_daily_rollups", ["rollup_date"], unique=False)
    op.create_index("ix_metrics_history_lookup", "metrics", ["device_id", "metric_name", "checked_at"], unique=False)
    op.create_index("ix_metrics_checked_at", "metrics", ["checked_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_metrics_checked_at", table_name="metrics")
    op.drop_index("ix_metrics_history_lookup", table_name="metrics")
    op.drop_index(op.f("ix_metric_daily_rollups_rollup_date"), table_name="metric_daily_rollups")
    op.drop_index(op.f("ix_metric_daily_rollups_device_id"), table_name="metric_daily_rollups")
    op.drop_index(op.f("ix_metric_daily_rollups_id"), table_name="metric_daily_rollups")
    op.drop_table("metric_daily_rollups")
