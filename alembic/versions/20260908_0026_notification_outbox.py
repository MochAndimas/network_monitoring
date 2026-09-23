"""Add durable notification outbox infrastructure; no automatic delivery enabled.

Revision ID: 20260908_0026
Revises: 20260908_0025
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "20260908_0026"
down_revision = "20260908_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql")
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("stream_key", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", timestamp, nullable=False),
        sa.Column("lease_until", timestamp, nullable=True),
        sa.Column("lease_token", sa.String(32), nullable=True),
        sa.Column("last_error", sa.String(50), nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.Column("delivered_at", timestamp, nullable=True),
    )
    op.create_index("uq_notification_outbox_key", "notification_outbox", ["idempotency_key"], unique=True)
    op.create_index("ix_notification_outbox_due", "notification_outbox", ["channel", "status", "available_at", "id"])
    op.create_index("ix_notification_outbox_lease", "notification_outbox", ["channel", "status", "lease_until", "id"])
    op.create_index("ix_notification_outbox_stream", "notification_outbox", ["channel", "stream_key", "id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM notification_outbox")):
        raise RuntimeError("Cannot drop a populated notification outbox; export and reconcile jobs first.")
    op.drop_table("notification_outbox")
