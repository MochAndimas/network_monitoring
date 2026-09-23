"""Ownership migration preserves legacy history and refuses a lossy downgrade."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def _migration(filename):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("scheduler_migration_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_owner_migration_preserves_history_and_checks_downgrade():
    old = _migration("20260417_0012_scheduler_job_statuses.py")
    new = _migration("20260908_0025_scheduler_job_owners.py")
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                old.upgrade()
                connection.execute(
                    text("""
                    INSERT INTO scheduler_job_statuses
                    (id, job_name, consecutive_failures, last_error, is_running, updated_at)
                    VALUES (1, 'device_checks', 3, 'legacy failure', 0, '2026-09-08 00:00:00')
                """)
                )
                new.upgrade()
                row = connection.execute(text("SELECT * FROM scheduler_job_statuses WHERE id = 1")).mappings().one()
                assert row["agent_id"] == "central"
                assert row["last_error"] == "legacy failure"
                assert row["consecutive_failures"] == 3
                connection.execute(
                    text("""
                    INSERT INTO scheduler_job_statuses
                    (id, job_name, agent_id, agent_site, consecutive_failures, is_running, updated_at)
                    VALUES (2, 'device_checks', 'site-fixture', 'Branch A', 0, 0, '2026-09-08 00:00:00')
                """)
                )
                with pytest.raises(RuntimeError, match="agent rows exist"):
                    new.downgrade()
                assert connection.scalar(text("SELECT COUNT(*) FROM scheduler_job_statuses")) == 2
                # Explicit fixture reconciliation makes the lossless central-only downgrade possible.
                connection.execute(text("DELETE FROM scheduler_job_statuses WHERE id = 2"))
                new.downgrade()
                assert connection.scalar(text("SELECT last_error FROM scheduler_job_statuses")) == "legacy failure"
                new.upgrade()
                assert connection.scalar(text("SELECT agent_id FROM scheduler_job_statuses")) == "central"
    finally:
        engine.dispose()
