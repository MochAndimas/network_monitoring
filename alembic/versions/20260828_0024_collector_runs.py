"""add collector execution telemetry

Revision ID: 20260828_0024
Revises: 20260826_0023
"""

from alembic import op
import sqlalchemy as sa

revision = "20260828_0024"
down_revision = "20260826_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collector_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collector_name", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("metric_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_collector_runs_name_checked", "collector_runs", ["collector_name", "checked_at"])


def downgrade() -> None:
    op.drop_index("ix_collector_runs_name_checked", table_name="collector_runs")
    op.drop_table("collector_runs")
