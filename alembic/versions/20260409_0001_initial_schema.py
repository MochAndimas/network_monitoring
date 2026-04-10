"""initial schema

Revision ID: 20260409_0001
Revises: 
Create Date: 2026-04-09 11:35:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("ip_address", sa.String(length=50), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ip_address"),
    )
    op.create_index(op.f("ix_devices_id"), "devices", ["id"], unique=False)
    op.create_table(
        "thresholds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(op.f("ix_thresholds_id"), "thresholds", ["id"], unique=False)
    op.create_index(op.f("ix_thresholds_key"), "thresholds", ["key"], unique=False)
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alerts_device_id"), "alerts", ["device_id"], unique=False)
    op.create_index(op.f("ix_alerts_id"), "alerts", ["id"], unique=False)
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_incidents_device_id"), "incidents", ["device_id"], unique=False)
    op.create_index(op.f("ix_incidents_id"), "incidents", ["id"], unique=False)
    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("metric_value", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_metrics_device_id"), "metrics", ["device_id"], unique=False)
    op.create_index(op.f("ix_metrics_id"), "metrics", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_metrics_id"), table_name="metrics")
    op.drop_index(op.f("ix_metrics_device_id"), table_name="metrics")
    op.drop_table("metrics")
    op.drop_index(op.f("ix_incidents_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_device_id"), table_name="incidents")
    op.drop_table("incidents")
    op.drop_index(op.f("ix_alerts_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_device_id"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_index(op.f("ix_thresholds_key"), table_name="thresholds")
    op.drop_index(op.f("ix_thresholds_id"), table_name="thresholds")
    op.drop_table("thresholds")
    op.drop_index(op.f("ix_devices_id"), table_name="devices")
    op.drop_table("devices")
