"""add admin audit logs and user lifecycle fields

Revision ID: 20260417_0013
Revises: 20260417_0012
Create Date: 2026-04-17 15:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0013"
down_revision = "20260417_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("disabled_reason", sa.String(length=255), nullable=True))

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_kind", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(length=100), nullable=True),
        sa.Column("actor_role", sa.String(length=30), nullable=False),
        sa.Column("actor_api_key_name", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_audit_logs_action"), "admin_audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_admin_audit_logs_created_at"), "admin_audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_admin_audit_logs_id"), "admin_audit_logs", ["id"], unique=False)
    op.create_index(op.f("ix_admin_audit_logs_target_id"), "admin_audit_logs", ["target_id"], unique=False)
    op.create_index(op.f("ix_admin_audit_logs_target_type"), "admin_audit_logs", ["target_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_audit_logs_target_type"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_target_id"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_id"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_created_at"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_action"), table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
    op.drop_column("users", "disabled_reason")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "password_changed_at")
