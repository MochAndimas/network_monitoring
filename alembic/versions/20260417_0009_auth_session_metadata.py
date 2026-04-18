"""add auth session metadata

Revision ID: 20260417_0009
Revises: 20260417_0008
Create Date: 2026-04-17 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0009"
down_revision = "20260417_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("client_ip", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("auth_sessions", sa.Column("user_agent", sa.String(length=255), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("auth_sessions", "user_agent")
    op.drop_column("auth_sessions", "client_ip")
