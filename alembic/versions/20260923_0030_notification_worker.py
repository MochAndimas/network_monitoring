"""Durable multipart progress and notification worker heartbeat.

Revision ID: 20260923_0030
Revises: 20260908_0029
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT, DATETIME

revision = "20260923_0030"
down_revision = "20260908_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_outbox", sa.Column("next_part", sa.Integer(), nullable=False, server_default="0"))
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "notification_outbox", "message", existing_type=sa.Text(), type_=LONGTEXT(), existing_nullable=False
        )
    op.create_table(
        "notification_workers",
        sa.Column("worker_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql"), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM notification_outbox WHERE next_part > 0 AND status != 'sent'")
    ):
        raise RuntimeError("Drain multipart jobs before downgrading")
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM notification_outbox WHERE length(message) > 65535")):
        raise RuntimeError("Retain multipart payload schema until large jobs are retired")
    op.drop_table("notification_workers")
    op.drop_column("notification_outbox", "next_part")
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "notification_outbox", "message", existing_type=LONGTEXT(), type_=sa.Text(), existing_nullable=False
        )
