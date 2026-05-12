"""retention bucket progress markers

Revision ID: 20260512_0017
Revises: 20260504_0016
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260512_0017"
down_revision = "20260504_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retention_bucket_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bucket_kind", sa.String(length=20), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("bucket_date", sa.Date(), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bucket_kind",
            "device_id",
            "bucket_date",
            "metric_name",
            "status",
            "unit",
            name="uq_retention_bucket_progress_bucket",
        ),
    )
    op.create_index(op.f("ix_retention_bucket_progress_id"), "retention_bucket_progress", ["id"], unique=False)
    op.create_index(
        op.f("ix_retention_bucket_progress_bucket_kind"),
        "retention_bucket_progress",
        ["bucket_kind"],
        unique=False,
    )
    op.create_index(op.f("ix_retention_bucket_progress_device_id"), "retention_bucket_progress", ["device_id"], unique=False)
    op.create_index(
        op.f("ix_retention_bucket_progress_bucket_date"),
        "retention_bucket_progress",
        ["bucket_date"],
        unique=False,
    )
    op.create_index(
        "ix_retention_bucket_progress_lookup",
        "retention_bucket_progress",
        ["bucket_kind", "bucket_date", "device_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_retention_bucket_progress_lookup", table_name="retention_bucket_progress")
    op.drop_index(op.f("ix_retention_bucket_progress_bucket_date"), table_name="retention_bucket_progress")
    op.drop_index(op.f("ix_retention_bucket_progress_device_id"), table_name="retention_bucket_progress")
    op.drop_index(op.f("ix_retention_bucket_progress_bucket_kind"), table_name="retention_bucket_progress")
    op.drop_index(op.f("ix_retention_bucket_progress_id"), table_name="retention_bucket_progress")
    op.drop_table("retention_bucket_progress")
