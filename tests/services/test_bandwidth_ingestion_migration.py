"""Schema parity, reversible empty upgrade, and replay-history preservation."""

import runpy
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from backend.app.db.base import Base
from backend.app.models.bandwidth import BandwidthClient
from backend.app.models.bandwidth_ingestion import (
    BandwidthFlow,
    BandwidthFlowRejection,
    BandwidthFlowSegment,
    BandwidthFlowStream,
)
from backend.app.models.device import Device


def test_ingestion_migration_roundtrip_and_model_parity():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261015_0032_bandwidth_ingestion.py"
    migration = runpy.run_path(str(path))
    names = {
        model.__tablename__
        for model in (
            BandwidthFlow,
            BandwidthFlowRejection,
            BandwidthFlowSegment,
            BandwidthFlowStream,
        )
    }
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            Device.__table__.create(connection)
            BandwidthClient.__table__.create(connection)
            with Operations.context(MigrationContext.configure(connection)):
                migration["upgrade"]()
                context = MigrationContext.configure(
                    connection,
                    opts={
                        "compare_type": True,
                        "include_object": lambda obj, name, kind, reflected, compare_to: kind != "table"
                        or name in names,
                    },
                )
                assert compare_metadata(context, Base.metadata) == []
                migration["downgrade"]()
                migration["upgrade"]()
                connection.execute(
                    text(
                        "INSERT INTO bandwidth_flow_streams "
                        "(stream_id,router_id,policy_digest,heartbeat_ns,status) VALUES ('fixture',1,'digest',1,'idle')"
                    )
                )
                with pytest.raises(RuntimeError, match="populated flow"):
                    migration["downgrade"]()
                assert connection.scalar(text("SELECT COUNT(*) FROM bandwidth_flow_streams")) == 1
    finally:
        engine.dispose()
