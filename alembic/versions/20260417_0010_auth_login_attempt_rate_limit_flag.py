"""add auth login attempt rate limit flag

Revision ID: 20260417_0010
Revises: 20260417_0009
Create Date: 2026-04-17 12:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0010"
down_revision = "20260417_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_login_attempts",
        sa.Column("was_rate_limited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("auth_login_attempts", "was_rate_limited")
