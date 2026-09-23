"""Attach immutable alert references to notification jobs.

Revision ID: 20260908_0027
Revises: 20260908_0026
"""

from alembic import op
import sqlalchemy as sa

revision = "20260908_0027"
down_revision = "20260908_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox_alerts",
        sa.Column(
            "outbox_id", sa.Integer(), sa.ForeignKey("notification_outbox.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("alert_id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(30), primary_key=True),
    )
    op.create_index("ix_outbox_alert_reference", "notification_outbox_alerts", ["alert_id", "action", "outbox_id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM notification_outbox_alerts")):
        raise RuntimeError("Cannot discard populated outbox alert references; reconcile notification jobs first.")
    op.drop_table("notification_outbox_alerts")
