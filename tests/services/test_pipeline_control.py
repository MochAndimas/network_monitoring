"""Lock failure must prevent writes and release partially acquired resources."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import OperationalError

from backend.app.scheduler import jobs
from backend.app.services import pipeline_control as locks
from tests.test_utils import run


def test_scheduler_retries_metric_lock_timeout_after_rollback(monkeypatch):
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setattr(jobs, "sleep", AsyncMock())
    db = SimpleNamespace(add=Mock(), commit=AsyncMock(), rollback=AsyncMock())
    runner = AsyncMock(return_value=[])
    evaluate = AsyncMock()
    monkeypatch.setattr(jobs, "evaluate_alerts", evaluate)
    calls = []

    async def persist(*args, **kwargs):
        calls.append("persist")
        if len(calls) == 1:
            raise OperationalError("INSERT", {}, Exception(1205, "lock timeout"))
        db.rollback.assert_awaited_once()

    monkeypatch.setattr(jobs, "persist_metrics", persist)
    run(jobs._persist_runner(runner, db, lock_scope="internet"))
    assert calls == ["persist", "persist"]
    runner.assert_awaited_once()
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    evaluate.assert_not_awaited()


@pytest.mark.parametrize("failures", [1, 2])
def test_device_scheduler_commits_independently_and_retries_only_failed_device(monkeypatch, failures):
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setattr(jobs, "sleep", AsyncMock())
    calls = []
    db = SimpleNamespace(
        add=Mock(), commit=AsyncMock(side_effect=lambda: calls.append("commit")),
        rollback=AsyncMock(side_effect=lambda: calls.append("rollback")),
    )
    attempts = 0

    async def persist(session, batch, *, commit):
        nonlocal attempts
        assert session is db and commit is False
        device_id = batch[0]["device_id"]
        assert all(metric["device_id"] == device_id for metric in batch)
        calls.append((device_id, len(batch)))
        if device_id == 2:
            attempts += 1
            if attempts <= failures:
                raise OperationalError("INSERT", {}, Exception(1205, "lock timeout"))

    monkeypatch.setattr(jobs, "persist_metrics", persist)
    monkeypatch.setattr(
        jobs, "run_device_checks", AsyncMock(return_value=[{"device_id": i} for i in (3, 1, 2, 1)])
    )

    async def dispatch(name, operation):
        assert name == "device_checks"
        await operation(db)

    monkeypatch.setattr(jobs, "_run_scheduler_job", dispatch)
    if failures == 2:
        with pytest.raises(RuntimeError, match="3/4 metrics committed"):
            run(jobs.run_device_job())
    else:
        run(jobs.run_device_job())

    assert calls == [
        (1, 2), "commit", (2, 1), "rollback", (2, 1),
        "rollback" if failures == 2 else "commit", (3, 1), "commit", "commit",
    ]
    report = db.add.call_args.args[0]
    assert (report.status, report.metric_count) == (("partial", 3) if failures == 2 else ("ok", 4))


def test_mysql_release_failure_preserves_operation_error(monkeypatch, caplog):
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    monkeypatch.setattr(locks, "_acquire_mysql_lock", AsyncMock(return_value=(object(), True)))
    monkeypatch.setattr(locks, "_release_mysql_lock", AsyncMock(side_effect=RuntimeError("release failed")))

    async def scenario():
        async with locks.monitoring_pipeline_guard(wait=False, scope="cleanup"):
            raise ValueError("operation failed")

    with pytest.raises(ValueError, match="operation failed"):
        run(scenario())
    assert "Failed to release MySQL advisory lock" in caplog.text


def test_scheduler_metric_lock_timeout_prevents_writes(monkeypatch):
    scope = "metrics:device:central"
    acquisition = AsyncMock(return_value=(None, False))
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    monkeypatch.setattr(locks, "_acquire_mysql_lock", acquisition)
    persist = AsyncMock()
    evaluate = AsyncMock()
    monkeypatch.setattr(jobs, "persist_metrics", persist)
    monkeypatch.setattr(jobs, "evaluate_alerts", evaluate)
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())

    operation = jobs._persist_runner(AsyncMock(return_value=[]), db, lock_scope="device:central")
    with pytest.raises(locks.PipelineLockTimeoutError, match=scope):
        run(operation)
    acquisition.assert_awaited_once_with(wait=True, scope=scope)
    evaluate.assert_not_awaited()
    persist.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


def test_multi_guard_releases_earlier_lock_on_blocking_failure(monkeypatch):
    connection = SimpleNamespace(execute=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    monkeypatch.setattr(locks, "_acquire_mysql_lock", AsyncMock(side_effect=[(connection, True), (None, False)]))

    async def scenario():
        with pytest.raises(locks.PipelineLockTimeoutError, match="b"):
            async with locks.monitoring_pipeline_multi_guard(wait=True, scopes=("b", "a")):
                pytest.fail("Partial acquisition must not enter the critical section")

    run(scenario())
    connection.execute.assert_awaited_once()
    connection.close.assert_awaited_once()


def test_local_blocking_timeout_preserves_owner_and_allows_retry(monkeypatch):
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setattr(locks, "_monitoring_pipeline_locks", {})
    monkeypatch.setattr(locks, "_lock_timeout_seconds", lambda **kwargs: 0.01)

    async def scenario():
        before = locks.pipeline_lock_health()["contention_count"]
        async with locks.monitoring_pipeline_guard(wait=False, scope="test") as acquired:
            assert acquired
            with pytest.raises(locks.PipelineLockTimeoutError):
                async with locks.monitoring_pipeline_guard(wait=True, scope="test"):
                    pytest.fail("Timeout must not enter the critical section")
            assert locks._process_lock_for_scope("test").locked()
        async with locks.monitoring_pipeline_guard(wait=True, scope="test") as acquired:
            assert acquired
        assert locks.pipeline_lock_health()["contention_count"] == before + 1

    run(scenario())


@pytest.mark.parametrize("error", [RuntimeError("database unavailable"), asyncio.CancelledError()])
def test_failed_mysql_acquisition_discards_connection(monkeypatch, error):
    connection = AsyncMock()
    connection.execute.side_effect = error
    monkeypatch.setattr(locks, "engine", SimpleNamespace(connect=AsyncMock(return_value=connection)))

    with pytest.raises(type(error)):
        run(locks._acquire_mysql_lock(wait=True, scope="test"))

    connection.invalidate.assert_awaited_once()
    connection.close.assert_awaited_once()


@pytest.mark.parametrize("error", [RuntimeError("database unavailable"), asyncio.CancelledError()])
def test_failed_mysql_release_discards_connection(error):
    connection = AsyncMock()
    connection.execute.side_effect = error

    with pytest.raises(type(error)):
        run(locks._release_mysql_lock(connection, scope="test"))

    connection.invalidate.assert_awaited_once()
    connection.close.assert_awaited_once()


def test_mysql_timeout_closes_unowned_connection(monkeypatch):
    result = Mock()
    result.scalar.return_value = 0
    connection = SimpleNamespace(execute=AsyncMock(return_value=result), close=AsyncMock(), invalidate=AsyncMock())
    monkeypatch.setattr(locks, "engine", SimpleNamespace(connect=AsyncMock(return_value=connection)))
    assert run(locks._acquire_mysql_lock(wait=True, scope="test")) == (None, False)
    connection.close.assert_awaited_once()
    connection.invalidate.assert_not_awaited()


@pytest.mark.parametrize("acquired", [True, False])
def test_cleanup_scheduler_uses_batch_transactions_and_keeps_guard(monkeypatch, acquired):
    from contextlib import asynccontextmanager

    inside = False

    @asynccontextmanager
    async def guard(*, wait, scope):
        nonlocal inside
        assert wait is False and scope == "cleanup"
        inside = True
        try:
            yield acquired
        finally:
            inside = False

    async def cleanup(db, *, commit=True):
        assert inside and commit is True

    monitoring = AsyncMock(side_effect=cleanup)
    auth = AsyncMock(side_effect=cleanup)
    monkeypatch.setattr(jobs, "monitoring_pipeline_guard", guard)
    monkeypatch.setattr(jobs, "cleanup_monitoring_data", monitoring)
    monkeypatch.setattr(jobs, "cleanup_auth_data", auth)
    db = SimpleNamespace(commit=AsyncMock())
    run(jobs._run_cleanup_job_inner(db))
    assert monitoring.await_count == auth.await_count == int(acquired)
    db.commit.assert_not_awaited()
    assert not inside
