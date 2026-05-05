"""track telegram alert notification state

Revision ID: 20260504_0016
Revises: 20260422_0015
Create Date: 2026-05-04 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260504_0016"
down_revision = "20260422_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the requested operation for Alembic database migrations."""
    bind = op.get_bind()
    inspector = inspect(bind)
    alert_columns = {column["name"] for column in inspector.get_columns("alerts")}
    if "telegram_notified_at" not in alert_columns:
        op.add_column("alerts", sa.Column("telegram_notified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Revert the requested operation for Alembic database migrations."""
    bind = op.get_bind()
    inspector = inspect(bind)
    alert_columns = {column["name"] for column in inspector.get_columns("alerts")}
    if "telegram_notified_at" in alert_columns:
        op.drop_column("alerts", "telegram_notified_at")
