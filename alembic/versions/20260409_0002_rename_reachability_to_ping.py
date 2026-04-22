"""rename reachability metric to ping

Revision ID: 20260409_0002
Revises: 20260409_0001
Create Date: 2026-04-09 12:45:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0002"
down_revision = "20260409_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the requested operation for Alembic database migrations.

    Returns:
        None. The routine is executed for its side effects.
    """
    op.execute(
        sa.text(
            "UPDATE metrics SET metric_name = 'ping' WHERE metric_name = 'reachability'"
        )
    )


def downgrade() -> None:
    """Revert the requested operation for Alembic database migrations.

    Returns:
        None. The routine is executed for its side effects.
    """
    op.execute(
        sa.text(
            "UPDATE metrics SET metric_name = 'reachability' WHERE metric_name = 'ping'"
        )
    )
