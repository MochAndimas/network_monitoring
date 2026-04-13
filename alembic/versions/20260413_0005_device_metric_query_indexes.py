"""add device and metric query optimization indexes

Revision ID: 20260413_0005
Revises: 20260413_0004
Create Date: 2026-04-13 00:20:00
"""
from __future__ import annotations

from alembic import op


revision = "20260413_0005"
down_revision = "20260413_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_devices_active_type_name", "devices", ["is_active", "device_type", "name"], unique=False)
    op.create_index("ix_metrics_name_device_checked", "metrics", ["metric_name", "device_id", "checked_at"], unique=False)
    op.create_index("ix_metrics_history_status_checked", "metrics", ["status", "checked_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_metrics_history_status_checked", table_name="metrics")
    op.drop_index("ix_metrics_name_device_checked", table_name="metrics")
    op.drop_index("ix_devices_active_type_name", table_name="devices")
