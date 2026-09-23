"""Separate scheduler health by collector owner.

Revision ID: 20260908_0025
Revises: 20260828_0024
"""

from alembic import op
import sqlalchemy as sa

revision = "20260908_0025"
down_revision = "20260828_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduler_job_statuses", sa.Column("agent_id", sa.String(64), nullable=False, server_default="central")
    )
    op.add_column("scheduler_job_statuses", sa.Column("agent_site", sa.String(100), nullable=True))
    op.add_column("scheduler_job_statuses", sa.Column("expected_interval_seconds", sa.Integer(), nullable=True))
    op.drop_index("ix_scheduler_job_statuses_job_name", table_name="scheduler_job_statuses")
    op.create_index("ix_scheduler_job_statuses_job_name", "scheduler_job_statuses", ["job_name"])
    op.create_index("uq_scheduler_job_owner", "scheduler_job_statuses", ["job_name", "agent_id"], unique=True)


def downgrade() -> None:
    # Refuse silent loss of per-agent history or an ambiguous merge into one row.
    connection = op.get_bind()
    agent_rows = connection.scalar(sa.text("SELECT COUNT(*) FROM scheduler_job_statuses WHERE agent_id <> 'central'"))
    if agent_rows:
        raise RuntimeError(
            "Cannot downgrade scheduler ownership while agent rows exist; export and reconcile them first."
        )
    op.drop_index("uq_scheduler_job_owner", table_name="scheduler_job_statuses")
    op.drop_index("ix_scheduler_job_statuses_job_name", table_name="scheduler_job_statuses")
    op.create_index("ix_scheduler_job_statuses_job_name", "scheduler_job_statuses", ["job_name"], unique=True)
    op.drop_column("scheduler_job_statuses", "expected_interval_seconds")
    op.drop_column("scheduler_job_statuses", "agent_site")
    op.drop_column("scheduler_job_statuses", "agent_id")
