"""add covering index for latest metric history lookups

Revision ID: 20260422_0014
Revises: 20260417_0013
Create Date: 2026-04-22 14:20:00
"""
from __future__ import annotations

from alembic import op


revision = "20260422_0014"
down_revision = "20260417_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_metrics_history_lookup_with_id",
        "metrics",
        ["device_id", "metric_name", "checked_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_metrics_history_lookup_with_id", table_name="metrics")
