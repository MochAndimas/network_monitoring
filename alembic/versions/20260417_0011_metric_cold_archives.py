"""add metric cold archives

Revision ID: 20260417_0011
Revises: 20260417_0010
Create Date: 2026-04-17 13:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_0011"
down_revision = "20260417_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_cold_archives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("archive_date", sa.Date(), nullable=False),
        sa.Column("archive_month", sa.Date(), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("numeric_sample_count", sa.Integer(), nullable=False),
        sa.Column("min_numeric_value", sa.Float(), nullable=True),
        sa.Column("max_numeric_value", sa.Float(), nullable=True),
        sa.Column("avg_numeric_value", sa.Float(), nullable=True),
        sa.Column("first_checked_at", sa.DateTime(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=False),
        sa.Column("last_metric_value", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id",
            "archive_date",
            "metric_name",
            "status",
            "unit",
            name="uq_metric_cold_archives_device_date_metric_status_unit",
        ),
    )
    op.create_index(op.f("ix_metric_cold_archives_archive_date"), "metric_cold_archives", ["archive_date"], unique=False)
    op.create_index(op.f("ix_metric_cold_archives_archive_month"), "metric_cold_archives", ["archive_month"], unique=False)
    op.create_index(op.f("ix_metric_cold_archives_device_id"), "metric_cold_archives", ["device_id"], unique=False)
    op.create_index(op.f("ix_metric_cold_archives_id"), "metric_cold_archives", ["id"], unique=False)
    op.create_index(op.f("ix_metric_cold_archives_metric_name"), "metric_cold_archives", ["metric_name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_metric_cold_archives_metric_name"), table_name="metric_cold_archives")
    op.drop_index(op.f("ix_metric_cold_archives_id"), table_name="metric_cold_archives")
    op.drop_index(op.f("ix_metric_cold_archives_device_id"), table_name="metric_cold_archives")
    op.drop_index(op.f("ix_metric_cold_archives_archive_month"), table_name="metric_cold_archives")
    op.drop_index(op.f("ix_metric_cold_archives_archive_date"), table_name="metric_cold_archives")
    op.drop_table("metric_cold_archives")
