"""add jwt id to auth sessions

Revision ID: 20260417_0007
Revises: 20260416_0006
Create Date: 2026-04-17 10:45:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0007"
down_revision = "20260416_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("jwt_id", sa.String(length=36), nullable=True))
    op.alter_column("auth_sessions", "token_hash", existing_type=sa.String(length=64), nullable=True)
    op.create_index("ix_auth_sessions_jwt_id", "auth_sessions", ["jwt_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_jwt_id", table_name="auth_sessions")
    op.alter_column("auth_sessions", "token_hash", existing_type=sa.String(length=64), nullable=False)
    op.drop_column("auth_sessions", "jwt_id")
