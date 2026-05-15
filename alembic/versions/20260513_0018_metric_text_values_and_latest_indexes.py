"""widen metric values and add latest metric query indexes

Revision ID: 20260513_0018
Revises: 20260512_0017
Create Date: 2026-05-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260513_0018"
down_revision = "20260512_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    with op.batch_alter_table("metrics") as batch_op:
        batch_op.alter_column(
            "metric_value",
            existing_type=sa.String(length=100),
            type_=sa.Text(),
            existing_nullable=False,
        )

    if inspector.has_table("latest_metrics"):
        with op.batch_alter_table("latest_metrics") as batch_op:
            batch_op.alter_column(
                "metric_value",
                existing_type=sa.String(length=100),
                type_=sa.Text(),
                existing_nullable=False,
            )
        latest_indexes = {index["name"] for index in inspect(bind).get_indexes("latest_metrics")}
        if "ix_latest_metrics_device_metric_checked" not in latest_indexes:
            op.create_index(
                "ix_latest_metrics_device_metric_checked",
                "latest_metrics",
                ["device_id", "metric_name", "checked_at"],
                unique=False,
            )

    if inspector.has_table("metric_cold_archives"):
        with op.batch_alter_table("metric_cold_archives") as batch_op:
            batch_op.alter_column(
                "last_metric_value",
                existing_type=sa.String(length=100),
                type_=sa.Text(),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("metric_cold_archives"):
        with op.batch_alter_table("metric_cold_archives") as batch_op:
            batch_op.alter_column(
                "last_metric_value",
                existing_type=sa.Text(),
                type_=sa.String(length=100),
                existing_nullable=False,
            )

    if inspector.has_table("latest_metrics"):
        latest_indexes = {index["name"] for index in inspector.get_indexes("latest_metrics")}
        if "ix_latest_metrics_device_metric_checked" in latest_indexes:
            op.drop_index("ix_latest_metrics_device_metric_checked", table_name="latest_metrics")
        with op.batch_alter_table("latest_metrics") as batch_op:
            batch_op.alter_column(
                "metric_value",
                existing_type=sa.Text(),
                type_=sa.String(length=100),
                existing_nullable=False,
            )

    with op.batch_alter_table("metrics") as batch_op:
        batch_op.alter_column(
            "metric_value",
            existing_type=sa.Text(),
            type_=sa.String(length=100),
            existing_nullable=False,
        )
