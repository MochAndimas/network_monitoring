"""Snapshot notification destinations and serialize producers until commit.

Revision ID: 20260908_0029
Revises: 20260908_0028
"""

from alembic import op
import sqlalchemy as sa

revision = "20260908_0029"
down_revision = "20260908_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy jobs have no snapshotted destination; never invent one from today's
    # runtime settings. They continue through the explicit legacy sender only.
    op.add_column("notification_outbox", sa.Column("destination", sa.String(255), nullable=True))
    op.create_table(
        "notification_outbox_streams",
        sa.Column("channel", sa.String(30), primary_key=True),
        sa.Column("stream_key", sa.String(128), primary_key=True),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM notification_outbox WHERE destination IS NOT NULL")):
        raise RuntimeError("Cannot discard snapshotted notification destinations; reconcile jobs first")
    op.drop_table("notification_outbox_streams")
    op.drop_column("notification_outbox", "destination")
