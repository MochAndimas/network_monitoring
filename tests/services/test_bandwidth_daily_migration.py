"""Daily schema parity and repeatable backfill of retained raw flows."""

import os
import runpy
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url

from backend.app.db.base import Base
from backend.app.models.bandwidth import BandwidthClient
from backend.app.models.bandwidth_daily import BandwidthDailyUsage
from backend.app.models.bandwidth_ingestion import BandwidthFlow, BandwidthFlowSegment, BandwidthFlowStream
from backend.app.models.device import Device


def test_daily_migration_backfill_roundtrip_and_parity():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261015_0033_bandwidth_daily.py"
    migration = runpy.run_path(str(path))
    url = make_url(os.environ.get("BANDWIDTH_TEST_DATABASE_URL", "sqlite:///:memory:"))
    if url.get_backend_name() != "sqlite":
        if not (url.database or "").endswith("_test"):
            raise ValueError("Migration test requires a disposable database ending in _test")
        url = url.set(drivername="mysql+pymysql")
    engine = create_engine(url)
    models = (Device, BandwidthClient, BandwidthFlowStream, BandwidthFlowSegment, BandwidthFlow)
    try:
        with engine.begin() as connection:
            for model in models:
                model.__table__.create(connection)
            connection.execute(
                Device.__table__.insert(),
                dict(
                    id=1,
                    name="Test router",
                    ip_address="192.0.2.1",
                    device_type="mikrotik",
                ),
            )
            connection.execute(
                BandwidthFlowStream.__table__.insert(),
                dict(
                    stream_id="fixture",
                    router_id=1,
                    policy_digest="fixture",
                    heartbeat_ns=1,
                    status="idle",
                ),
            )
            connection.execute(
                BandwidthFlowSegment.__table__.insert(),
                dict(
                    stream_id="fixture",
                    segment_id="fixture",
                    checksum="fixture",
                    size_bytes=1,
                    offset_bytes=1,
                    accepted_count=1,
                    rejected_count=0,
                    completed=True,
                ),
            )
            connection.execute(
                BandwidthFlow.__table__.insert(),
                dict(
                    id=1,
                    stream_id="fixture",
                    segment_id="fixture",
                    record_offset=0,
                    router_id=1,
                    client_id=None,
                    direction="upload",
                    device_ip="192.168.1.2",
                    remote_ip="1.1.1.1",
                    source_ip="192.168.1.2",
                    destination_ip="1.1.1.1",
                    input_interface=13,
                    output_interface=10,
                    byte_count=101,
                    packets=1,
                    started_ns=1_791_997_200_000_000_000 - 10,
                    ended_ns=1_791_997_200_000_000_000 + 20,
                    received_ns=1_791_997_200_000_000_100,
                ),
            )
            with Operations.context(MigrationContext.configure(connection)):
                for _ in range(2):
                    migration["upgrade"]()
                    context = MigrationContext.configure(
                        connection,
                        opts={
                            "compare_type": True,
                            "include_object": lambda obj, name, kind, reflected, compare_to: kind != "table"
                            or name == "bandwidth_daily_usage",
                        },
                    )
                    assert compare_metadata(context, Base.metadata) == []
                    rows = (
                        connection.execute(select(BandwidthDailyUsage.upload_bytes).order_by(BandwidthDailyUsage.day))
                        .scalars()
                        .all()
                    )
                    assert rows == [33, 68]
                    assert sum(connection.execute(select(BandwidthDailyUsage.estimated_bytes)).scalars()) == 101
                    migration["downgrade"]()
    finally:
        with engine.begin() as connection:
            BandwidthDailyUsage.__table__.drop(connection, checkfirst=True)
            for model in reversed(models):
                model.__table__.drop(connection, checkfirst=True)
        engine.dispose()
