"""add optional device location

Revision ID: 20260826_0023
Revises: 20260617_0022
Create Date: 2026-08-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260826_0023"
down_revision = "20260617_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("location", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "location")
