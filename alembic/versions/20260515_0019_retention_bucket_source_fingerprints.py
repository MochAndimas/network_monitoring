"""retention bucket source fingerprints

Revision ID: 20260515_0019
Revises: 20260513_0018
Create Date: 2026-05-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260515_0019"
down_revision = "20260513_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "retention_bucket_progress",
        sa.Column("source_metric_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("retention_bucket_progress", sa.Column("source_max_metric_id", sa.Integer(), nullable=True))
    op.add_column("retention_bucket_progress", sa.Column("source_latest_checked_at", sa.DateTime(), nullable=True))
    op.alter_column("retention_bucket_progress", "source_metric_count", server_default=None)

    op.add_column(
        "metric_daily_rollups",
        sa.Column("ping_numeric_samples", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "metric_daily_rollups",
        sa.Column("packet_loss_samples", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "metric_daily_rollups",
        sa.Column("packet_loss_numeric_samples", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "metric_daily_rollups",
        sa.Column("jitter_samples", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "metric_daily_rollups",
        sa.Column("jitter_numeric_samples", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("metric_daily_rollups", "ping_numeric_samples", server_default=None)
    op.alter_column("metric_daily_rollups", "packet_loss_samples", server_default=None)
    op.alter_column("metric_daily_rollups", "packet_loss_numeric_samples", server_default=None)
    op.alter_column("metric_daily_rollups", "jitter_samples", server_default=None)
    op.alter_column("metric_daily_rollups", "jitter_numeric_samples", server_default=None)


def downgrade() -> None:
    op.drop_column("metric_daily_rollups", "jitter_numeric_samples")
    op.drop_column("metric_daily_rollups", "jitter_samples")
    op.drop_column("metric_daily_rollups", "packet_loss_numeric_samples")
    op.drop_column("metric_daily_rollups", "packet_loss_samples")
    op.drop_column("metric_daily_rollups", "ping_numeric_samples")
    op.drop_column("retention_bucket_progress", "source_latest_checked_at")
    op.drop_column("retention_bucket_progress", "source_max_metric_id")
    op.drop_column("retention_bucket_progress", "source_metric_count")
