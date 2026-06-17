"""incident workflow fields and timeline

Revision ID: 20260617_0020
Revises: 20260515_0019
Create Date: 2026-06-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260617_0020"
down_revision = "20260515_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("owner", sa.String(length=100), nullable=True))
    op.add_column("incidents", sa.Column("assignee", sa.String(length=100), nullable=True))
    op.add_column("incidents", sa.Column("severity_override", sa.String(length=20), nullable=True))
    op.add_column("incidents", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
    op.add_column("incidents", sa.Column("acknowledged_by", sa.String(length=100), nullable=True))
    op.add_column("incidents", sa.Column("resolved_by", sa.String(length=100), nullable=True))
    op.add_column(
        "incidents",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.alter_column("incidents", "updated_at", server_default=None)
    op.create_index(
        "ix_incidents_ack_status_started_at",
        "incidents",
        ["status", "acknowledged_at", "started_at"],
    )

    op.create_table(
        "incident_timeline_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("event_metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_incident_timeline_events_id"), "incident_timeline_events", ["id"])
    op.create_index(
        "ix_incident_timeline_incident_created",
        "incident_timeline_events",
        ["incident_id", "created_at"],
    )
    op.create_index(
        "ix_incident_timeline_event_type_created",
        "incident_timeline_events",
        ["event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_incident_timeline_event_type_created", table_name="incident_timeline_events")
    op.drop_index("ix_incident_timeline_incident_created", table_name="incident_timeline_events")
    op.drop_index(op.f("ix_incident_timeline_events_id"), table_name="incident_timeline_events")
    op.drop_table("incident_timeline_events")

    op.drop_index("ix_incidents_ack_status_started_at", table_name="incidents")
    op.drop_column("incidents", "updated_at")
    op.drop_column("incidents", "resolved_by")
    op.drop_column("incidents", "acknowledged_by")
    op.drop_column("incidents", "acknowledged_at")
    op.drop_column("incidents", "note")
    op.drop_column("incidents", "severity_override")
    op.drop_column("incidents", "assignee")
    op.drop_column("incidents", "owner")
