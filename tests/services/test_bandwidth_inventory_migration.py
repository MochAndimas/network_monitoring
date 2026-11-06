"""Upgrade/downgrade, schema parity and data-preserving rollback gate."""

import runpy
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from backend.app.db.base import Base
from backend.app.models.bandwidth import BandwidthClient, BandwidthInventoryState, BandwidthIPHistory
from backend.app.models.device import Device


def test_inventory_migration_roundtrip_and_model_parity():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261015_0031_bandwidth_inventory.py"
    migration = runpy.run_path(str(path))
    table_names = {item.__tablename__ for item in (BandwidthClient, BandwidthInventoryState, BandwidthIPHistory)}
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            Device.__table__.create(connection)
            with Operations.context(MigrationContext.configure(connection)):
                migration["upgrade"]()
                context = MigrationContext.configure(
                    connection,
                    opts={
                        "compare_type": True,
                        "include_object": lambda obj, name, kind, reflected, compare_to: kind != "table"
                        or name in table_names,
                    },
                )
                assert compare_metadata(context, Base.metadata) == []
                migration["downgrade"]()
                migration["upgrade"]()
                connection.execute(
                    text(
                        "INSERT INTO bandwidth_clients "
                        "(router_id, mac_address, first_seen_ns, last_seen_ns) "
                        "VALUES (1, '70:08:94:1B:9C:DF', 100, 100)"
                    )
                )
                with pytest.raises(RuntimeError, match="populated tables"):
                    migration["downgrade"]()
                assert connection.scalar(text("SELECT COUNT(*) FROM bandwidth_clients")) == 1
    finally:
        engine.dispose()
