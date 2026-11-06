"""Router-scoped client identities and observed IP ownership history.

Revision ID: 20261015_0031
Revises: 20260923_0030
"""

import sqlalchemy as sa

from alembic import op

revision = "20261015_0031"
down_revision = "20260923_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bandwidth_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("router_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("mac_address", sa.String(17), nullable=False),
        sa.Column("hostname", sa.String(255)),
        sa.Column("custom_name", sa.String(255)),
        sa.Column("first_seen_ns", sa.BigInteger(), nullable=False),
        sa.Column("last_seen_ns", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("router_id", "mac_address", name="uq_bw_client_router_mac"),
    )
    op.create_table(
        "bandwidth_client_ip_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("router_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("bandwidth_clients.id"), nullable=False),
        sa.Column("ip_address", sa.String(15), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("first_observed_ns", sa.BigInteger(), nullable=False),
        sa.Column("last_observed_ns", sa.BigInteger(), nullable=False),
        sa.Column("ended_ns", sa.BigInteger()),
        sa.Column("active_slot", sa.Integer()),
        sa.UniqueConstraint("router_id", "ip_address", "active_slot", name="uq_bw_ip_active"),
        sa.CheckConstraint("last_observed_ns >= first_observed_ns", name="ck_bw_ip_observation_order"),
        sa.CheckConstraint(
            "(active_slot IS NOT NULL AND active_slot = 1 AND ended_ns IS NULL) "
            "OR (active_slot IS NULL AND ended_ns IS NOT NULL)",
            name="ck_bw_ip_active_state",
        ),
    )
    op.create_index(
        "ix_bw_ip_router_time", "bandwidth_client_ip_history", ["router_id", "ip_address", "first_observed_ns"]
    )
    op.create_index("ix_bw_ip_router_active", "bandwidth_client_ip_history", ["router_id", "active_slot"])
    op.create_table(
        "bandwidth_inventory_states",
        sa.Column("router_id", sa.Integer(), sa.ForeignKey("devices.id"), primary_key=True),
        sa.Column("observed_ns", sa.BigInteger(), nullable=False),
        sa.Column("client_count", sa.Integer(), nullable=False),
        sa.Column("ambiguous_ip_count", sa.Integer(), nullable=False),
        sa.Column("invalid_row_count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    # Follow the repository's data-preserving downgrade convention.
    for table in ("bandwidth_clients", "bandwidth_client_ip_history", "bandwidth_inventory_states"):
        if op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("Export and explicitly retire bandwidth inventory before downgrading populated tables")
    op.drop_table("bandwidth_inventory_states")
    op.drop_index("ix_bw_ip_router_active", table_name="bandwidth_client_ip_history")
    op.drop_index("ix_bw_ip_router_time", table_name="bandwidth_client_ip_history")
    op.drop_table("bandwidth_client_ip_history")
    op.drop_table("bandwidth_clients")
