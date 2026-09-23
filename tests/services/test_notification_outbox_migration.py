"""An outbox migration must not silently discard queued or delivered history."""

from pathlib import Path
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_outbox_downgrade_refuses_populated_queue():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260908_0026_notification_outbox.py"
    migration = runpy.run_path(str(path))
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                migration["upgrade"]()
                db.execute(
                    text("""
                    INSERT INTO notification_outbox
                    (idempotency_key, stream_key, channel, message, available_at, created_at, updated_at)
                    VALUES ('fixture', 'device:1', 'telegram', 'fixture message',
                            '2026-09-08 00:00:00', '2026-09-08 00:00:00', '2026-09-08 00:00:00')
                """)
                )
                with pytest.raises(RuntimeError, match="populated notification outbox"):
                    migration["downgrade"]()
                assert db.scalar(text("SELECT message FROM notification_outbox")) == "fixture message"
                db.execute(text("DELETE FROM notification_outbox"))
                migration["downgrade"]()
                migration["upgrade"]()
                assert db.scalar(text("SELECT COUNT(*) FROM notification_outbox")) == 0
    finally:
        engine.dispose()


def test_alert_reference_downgrade_preserves_populated_history():
    versions = Path(__file__).resolve().parents[2] / "alembic/versions"
    queue = runpy.run_path(str(versions / "20260908_0026_notification_outbox.py"))
    references = runpy.run_path(str(versions / "20260908_0027_outbox_alert_references.py"))
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                queue["upgrade"]()
                references["upgrade"]()
                db.execute(
                    text("""
                    INSERT INTO notification_outbox
                    (id, idempotency_key, stream_key, channel, message, available_at, created_at, updated_at)
                    VALUES (1, 'fixture', 'device:1', 'telegram', 'fixture message',
                            '2026-09-08 00:00:00', '2026-09-08 00:00:00', '2026-09-08 00:00:00')
                """)
                )
                db.execute(text("INSERT INTO notification_outbox_alerts VALUES (1, 42, 'active')"))
                with pytest.raises(RuntimeError, match="populated outbox alert references"):
                    references["downgrade"]()
                assert db.scalar(text("SELECT alert_id FROM notification_outbox_alerts")) == 42
                db.execute(text("DELETE FROM notification_outbox_alerts"))
                references["downgrade"]()
                references["upgrade"]()
                assert db.scalar(text("SELECT COUNT(*) FROM notification_outbox_alerts")) == 0
                assert db.scalar(text("SELECT COUNT(*) FROM notification_outbox")) == 1
    finally:
        engine.dispose()


def test_routing_downgrade_preserves_snapshotted_destinations():
    versions = Path(__file__).resolve().parents[2] / "alembic/versions"
    queue = runpy.run_path(str(versions / "20260908_0026_notification_outbox.py"))
    routing = runpy.run_path(str(versions / "20260908_0029_outbox_routing_streams.py"))
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                queue["upgrade"]()
                routing["upgrade"]()
                db.execute(
                    text("""
                    INSERT INTO notification_outbox
                    (idempotency_key, stream_key, channel, message, destination, available_at, created_at, updated_at)
                    VALUES ('fixture', 'fixture', 'telegram', 'fixture', '123',
                            '2026-09-08 00:00:00', '2026-09-08 00:00:00', '2026-09-08 00:00:00')
                """)
                )
                with pytest.raises(RuntimeError, match="snapshotted notification destinations"):
                    routing["downgrade"]()
                assert db.scalar(text("SELECT destination FROM notification_outbox")) == "123"
                db.execute(text("DELETE FROM notification_outbox"))
                routing["downgrade"]()
                routing["upgrade"]()
                assert db.scalar(text("SELECT COUNT(*) FROM notification_outbox_streams")) == 0
    finally:
        engine.dispose()
