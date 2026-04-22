"""add alert and incident composite indexes

Revision ID: 20260413_0004
Revises: 20260410_0003
Create Date: 2026-04-13 00:04:00
"""
from __future__ import annotations

from alembic import op


revision = "20260413_0004"
down_revision = "20260410_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the requested operation for Alembic database migrations.

    Returns:
        None. The routine is executed for its side effects.
    """
    op.create_index("ix_alerts_status_created_at", "alerts", ["status", "created_at"], unique=False)
    op.create_index("ix_alerts_device_status_type", "alerts", ["device_id", "status", "alert_type"], unique=False)
    op.create_index("ix_incidents_status_started_at", "incidents", ["status", "started_at"], unique=False)
    op.create_index("ix_incidents_device_status", "incidents", ["device_id", "status"], unique=False)


def downgrade() -> None:
    """Revert the requested operation for Alembic database migrations.

    Returns:
        None. The routine is executed for its side effects.
    """
    op.drop_index("ix_incidents_device_status", table_name="incidents")
    op.drop_index("ix_incidents_status_started_at", table_name="incidents")
    op.drop_index("ix_alerts_device_status_type", table_name="alerts")
    op.drop_index("ix_alerts_status_created_at", table_name="alerts")
