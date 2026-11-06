"""Materialize WIB usage, including existing flows. Stop ingestion during upgrade.

Revision ID: 20261015_0033
Revises: 20261015_0032
"""

from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from alembic import op

revision = "20261015_0033"
down_revision = "20261015_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "bandwidth_daily_usage",
        sa.Column("router_id", sa.Integer(), sa.ForeignKey("devices.id"), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("subject", sa.String(32), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("bandwidth_clients.id")),
        sa.Column("unresolved_ip", sa.String(15)),
        sa.Column("upload_bytes", sa.Numeric(38, 0).with_variant(sa.BigInteger(), "sqlite"), nullable=False),
        sa.Column("download_bytes", sa.Numeric(38, 0).with_variant(sa.BigInteger(), "sqlite"), nullable=False),
        sa.Column("estimated_bytes", sa.Numeric(38, 0).with_variant(sa.BigInteger(), "sqlite"), nullable=False),
        sa.Column("updated_ns", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "upload_bytes >= 0 AND download_bytes >= 0 AND estimated_bytes >= 0", name="ck_bw_daily_bytes"
        ),
    )
    # Frozen allocation v1, deliberately independent of application imports.
    # Keyset batches avoid loading raw history into memory during upgrades.
    bind = op.get_bind()
    cursor = 0
    while True:
        flows = (
            bind.execute(
                sa.text(
                    "SELECT id,router_id,client_id,device_ip,direction,byte_count,started_ns,ended_ns,received_ns "
                    "FROM bandwidth_flows WHERE id > :cursor ORDER BY id LIMIT 500"
                ),
                {"cursor": cursor},
            )
            .mappings()
            .all()
        )
        if not flows:
            break
        for flow in flows:
            first = (flow["started_ns"] + 25_200_000_000_000) // 86_400_000_000_000
            last = (max(flow["started_ns"], flow["ended_ns"] - 1) + 25_200_000_000_000) // 86_400_000_000_000
            previous = 0
            for day in range(first, last + 1):
                boundary = min(flow["ended_ns"], (day + 1) * 86_400_000_000_000 - 25_200_000_000_000)
                duration = flow["ended_ns"] - flow["started_ns"]
                cumulative = (
                    flow["byte_count"]
                    if not duration
                    else flow["byte_count"] * (boundary - flow["started_ns"]) // duration
                )
                count, previous = cumulative - previous, cumulative
                if not count:
                    continue
                client = flow["client_id"]
                values = dict(
                    router_id=flow["router_id"],
                    day=date(1970, 1, 1) + timedelta(days=day),
                    subject=f"c:{client}" if client is not None else f"ip:{flow['device_ip']}",
                    client_id=client,
                    unresolved_ip=None if client is not None else flow["device_ip"],
                    upload_bytes=count if flow["direction"] == "upload" else 0,
                    download_bytes=count if flow["direction"] == "download" else 0,
                    estimated_bytes=count if first != last else 0,
                    updated_ns=flow["received_ns"],
                )
                if bind.dialect.name == "mysql":
                    statement = mysql_insert(table).values(**values)
                    bind.execute(
                        statement.on_duplicate_key_update(
                            **{
                                name: table.c[name] + statement.inserted[name]
                                for name in ("upload_bytes", "download_bytes", "estimated_bytes")
                            },
                            updated_ns=sa.func.greatest(table.c.updated_ns, statement.inserted.updated_ns),
                        )
                    )
                else:
                    statement_sqlite = sqlite_insert(table).values(**values)
                    bind.execute(
                        statement_sqlite.on_conflict_do_update(
                            index_elements=["router_id", "day", "subject"],
                            set_={
                                **{
                                    name: table.c[name] + statement_sqlite.excluded[name]
                                    for name in ("upload_bytes", "download_bytes", "estimated_bytes")
                                },
                                "updated_ns": sa.func.max(table.c.updated_ns, statement_sqlite.excluded.updated_ns),
                            },
                        )
                    )
        cursor = flows[-1]["id"]


def downgrade() -> None:
    # Derived rows can always be rebuilt from retained raw flows on upgrade.
    op.drop_table("bandwidth_daily_usage")
