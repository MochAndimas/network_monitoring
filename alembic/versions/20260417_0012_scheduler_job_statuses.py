"""add scheduler job statuses

Revision ID: 20260417_0012
Revises: 20260417_0011
Create Date: 2026-04-17 14:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0012"
down_revision = "20260417_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_job_statuses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(), nullable=True),
        sa.Column("last_duration_ms", sa.Float(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("is_running", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scheduler_job_statuses_id"), "scheduler_job_statuses", ["id"], unique=False)
    op.create_index(op.f("ix_scheduler_job_statuses_job_name"), "scheduler_job_statuses", ["job_name"], unique=True)
