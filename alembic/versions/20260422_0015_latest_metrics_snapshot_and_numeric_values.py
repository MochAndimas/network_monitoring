"""add latest_metrics snapshot table and numeric metric values

Revision ID: 20260422_0015
Revises: 20260422_0014
Create Date: 2026-04-22 16:15:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260422_0015"
down_revision = "20260422_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    inspector = inspect(bind)

    metric_columns = {column["name"] for column in inspector.get_columns("metrics")}
    if "metric_value_numeric" not in metric_columns:
        op.add_column("metrics", sa.Column("metric_value_numeric", sa.Float(), nullable=True))

    # Skip full-table numeric backfill in migration to avoid long write locks.
    # New rows are persisted with metric_value_numeric by application code.

    if not inspector.has_table("latest_metrics"):
        op.create_table(
            "latest_metrics",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("metric_id", sa.Integer(), sa.ForeignKey("metrics.id"), nullable=False),
            sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
            sa.Column("metric_name", sa.String(length=100), nullable=False),
            sa.Column("metric_value", sa.String(length=100), nullable=False),
            sa.Column("metric_value_numeric", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("unit", sa.String(length=30), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=False),
            sa.Column("uptime_streak_started_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("metric_id", name="uq_latest_metrics_metric_id"),
            sa.UniqueConstraint("device_id", "metric_name", name="uq_latest_metrics_device_metric"),
        )

    latest_metric_indexes = {index["name"] for index in inspect(bind).get_indexes("latest_metrics")}
    if "ix_latest_metrics_device_checked" not in latest_metric_indexes:
        op.create_index("ix_latest_metrics_device_checked", "latest_metrics", ["device_id", "checked_at"], unique=False)
    if "ix_latest_metrics_metric_checked" not in latest_metric_indexes:
        op.create_index("ix_latest_metrics_metric_checked", "latest_metrics", ["metric_name", "checked_at"], unique=False)
    if "ix_latest_metrics_status_checked" not in latest_metric_indexes:
        op.create_index("ix_latest_metrics_status_checked", "latest_metrics", ["status", "checked_at"], unique=False)
    if "ix_latest_metrics_metric_id" not in latest_metric_indexes:
        op.create_index("ix_latest_metrics_metric_id", "latest_metrics", ["metric_id"], unique=False)
    if "ix_latest_metrics_device_id" not in latest_metric_indexes:
        op.create_index("ix_latest_metrics_device_id", "latest_metrics", ["device_id"], unique=False)
    if "ix_latest_metrics_checked_at" not in latest_metric_indexes:
        op.create_index("ix_latest_metrics_checked_at", "latest_metrics", ["checked_at"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO latest_metrics (
                metric_id,
                device_id,
                metric_name,
                metric_value,
                metric_value_numeric,
                status,
                unit,
                checked_at,
                uptime_streak_started_at
            )
            SELECT ranked.id,
                   ranked.device_id,
                   ranked.metric_name,
                   ranked.metric_value,
                   ranked.metric_value_numeric,
                   ranked.status,
                   ranked.unit,
                   ranked.checked_at,
                   NULL
            FROM metrics ranked
            INNER JOIN (
                SELECT device_id,
                       metric_name,
                       MAX(checked_at) AS max_checked_at
                FROM metrics
                GROUP BY device_id, metric_name
            ) latest_checked
                ON latest_checked.device_id = ranked.device_id
               AND latest_checked.metric_name = ranked.metric_name
               AND latest_checked.max_checked_at = ranked.checked_at
            LEFT JOIN metrics tie_breaker
                ON tie_breaker.device_id = ranked.device_id
               AND tie_breaker.metric_name = ranked.metric_name
               AND tie_breaker.checked_at = ranked.checked_at
               AND tie_breaker.id > ranked.id
            LEFT JOIN latest_metrics existing
                ON existing.device_id = ranked.device_id
               AND existing.metric_name = ranked.metric_name
            WHERE tie_breaker.id IS NULL
              AND existing.id IS NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE latest_metrics lm
            SET uptime_streak_started_at = lm.checked_at
            WHERE lm.uptime_streak_started_at IS NULL
              AND LOWER(COALESCE(lm.status, '')) IN ('up', 'ok')
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("latest_metrics"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("latest_metrics")}
        if "ix_latest_metrics_checked_at" in existing_indexes:
            op.drop_index("ix_latest_metrics_checked_at", table_name="latest_metrics")
        if "ix_latest_metrics_device_id" in existing_indexes:
            op.drop_index("ix_latest_metrics_device_id", table_name="latest_metrics")
        if "ix_latest_metrics_metric_id" in existing_indexes:
            op.drop_index("ix_latest_metrics_metric_id", table_name="latest_metrics")
        if "ix_latest_metrics_status_checked" in existing_indexes:
            op.drop_index("ix_latest_metrics_status_checked", table_name="latest_metrics")
        if "ix_latest_metrics_metric_checked" in existing_indexes:
            op.drop_index("ix_latest_metrics_metric_checked", table_name="latest_metrics")
        if "ix_latest_metrics_device_checked" in existing_indexes:
            op.drop_index("ix_latest_metrics_device_checked", table_name="latest_metrics")
        op.drop_table("latest_metrics")

    metric_columns = {column["name"] for column in inspect(bind).get_columns("metrics")}
    if "metric_value_numeric" in metric_columns:
        op.drop_column("metrics", "metric_value_numeric")
