"""Add the optional metric bulk insert correlation token.

Revision ID: 20261112_0034
Revises: 20261015_0033
"""

import sqlalchemy as sa

from alembic import op

revision = "20261112_0034"
down_revision = "20261015_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().dialect.name == "mysql":
        op.execute(
            "ALTER TABLE metrics ADD COLUMN insert_token BINARY(16) NULL, "
            "ADD UNIQUE INDEX uq_metrics_insert_token (insert_token), ALGORITHM=INPLACE, LOCK=NONE"
        )
    else:
        op.add_column("metrics", sa.Column("insert_token", sa.LargeBinary(16), nullable=True))
        op.create_index("uq_metrics_insert_token", "metrics", ["insert_token"], unique=True)


def downgrade() -> None:
    if op.get_context().dialect.name == "mysql":
        op.execute("ALTER TABLE metrics DROP INDEX uq_metrics_insert_token, DROP COLUMN insert_token")
    else:
        op.drop_index("uq_metrics_insert_token", table_name="metrics")
        op.drop_column("metrics", "insert_token")
