"""phase4 data explorer summaries and indexes

Revision ID: 20260617_0022
Revises: 20260617_0021
Create Date: 2026-06-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260617_0022"
down_revision = "20260617_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_site_type_daily_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("device_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ping_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("down_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_uptime_percentage", sa.Float(), nullable=True),
        sa.Column("average_ping_ms", sa.Float(), nullable=True),
        sa.Column("average_packet_loss_percent", sa.Float(), nullable=True),
        sa.Column("average_jitter_ms", sa.Float(), nullable=True),
        sa.Column("max_jitter_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_date", "site", "device_type", name="uq_metric_site_type_daily_summary"),
    )
    op.create_index(op.f("ix_metric_site_type_daily_summaries_id"), "metric_site_type_daily_summaries", ["id"])
    op.create_index(
        "ix_metric_site_type_summary_date_site_type",
        "metric_site_type_daily_summaries",
        ["summary_date", "site", "device_type"],
    )
    op.create_index(
        "ix_metric_cold_archives_month_metric_site_lookup",
        "metric_cold_archives",
        ["archive_month", "metric_name", "device_id"],
    )
    op.create_index(
        "ix_metric_daily_rollups_date_device_lookup",
        "metric_daily_rollups",
        ["rollup_date", "device_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_metric_daily_rollups_date_device_lookup", table_name="metric_daily_rollups")
    op.drop_index("ix_metric_cold_archives_month_metric_site_lookup", table_name="metric_cold_archives")
    op.drop_index("ix_metric_site_type_summary_date_site_type", table_name="metric_site_type_daily_summaries")
    op.drop_index(op.f("ix_metric_site_type_daily_summaries_id"), table_name="metric_site_type_daily_summaries")
    op.drop_table("metric_site_type_daily_summaries")
