"""add auth login attempts

Revision ID: 20260417_0008
Revises: 20260417_0007
Create Date: 2026-04-17 11:15:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0008"
down_revision = "20260417_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("was_successful", sa.Boolean(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_login_attempts_attempted_at", "auth_login_attempts", ["attempted_at"], unique=False)
    op.create_index(
        "ix_auth_login_attempts_lookup",
        "auth_login_attempts",
        ["username", "client_ip", "attempted_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_login_attempts_cleanup",
        "auth_login_attempts",
        ["attempted_at", "was_successful"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_login_attempts_cleanup", table_name="auth_login_attempts")
    op.drop_index("ix_auth_login_attempts_lookup", table_name="auth_login_attempts")
    op.drop_index("ix_auth_login_attempts_attempted_at", table_name="auth_login_attempts")
    op.drop_table("auth_login_attempts")
