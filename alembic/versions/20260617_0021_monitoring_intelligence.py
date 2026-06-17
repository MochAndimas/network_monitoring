"""monitoring intelligence controls

Revision ID: 20260617_0021
Revises: 20260617_0020
Create Date: 2026-06-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260617_0021"
down_revision = "20260617_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "threshold_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("threshold_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("device_type", sa.String(length=50), nullable=True),
        sa.Column("site", sa.String(length=100), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_threshold_overrides_id"), "threshold_overrides", ["id"])
    op.create_index("ix_threshold_overrides_key_active", "threshold_overrides", ["threshold_key", "is_active"])
    op.create_index("ix_threshold_overrides_device_active", "threshold_overrides", ["device_id", "is_active"])
    op.create_index("ix_threshold_overrides_type_active", "threshold_overrides", ["device_type", "is_active"])
    op.create_index("ix_threshold_overrides_site_active", "threshold_overrides", ["site", "is_active"])

    op.create_table(
        "maintenance_windows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("site", sa.String(length=100), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_maintenance_windows_id"), "maintenance_windows", ["id"])
    op.create_index("ix_maintenance_windows_active_time", "maintenance_windows", ["is_active", "starts_at", "ends_at"])
    op.create_index("ix_maintenance_windows_device_active", "maintenance_windows", ["device_id", "is_active"])
    op.create_index("ix_maintenance_windows_site_active", "maintenance_windows", ["site", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_maintenance_windows_site_active", table_name="maintenance_windows")
    op.drop_index("ix_maintenance_windows_device_active", table_name="maintenance_windows")
    op.drop_index("ix_maintenance_windows_active_time", table_name="maintenance_windows")
    op.drop_index(op.f("ix_maintenance_windows_id"), table_name="maintenance_windows")
    op.drop_table("maintenance_windows")

    op.drop_index("ix_threshold_overrides_site_active", table_name="threshold_overrides")
    op.drop_index("ix_threshold_overrides_type_active", table_name="threshold_overrides")
    op.drop_index("ix_threshold_overrides_device_active", table_name="threshold_overrides")
    op.drop_index("ix_threshold_overrides_key_active", table_name="threshold_overrides")
    op.drop_index(op.f("ix_threshold_overrides_id"), table_name="threshold_overrides")
    op.drop_table("threshold_overrides")
