"""Lock failure must prevent writes and release partially acquired resources."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app.scheduler import jobs
from backend.app.services import pipeline_control as locks
from tests.test_utils import run


@pytest.mark.parametrize("scope", ["metrics:device:central", "alerts"])
def test_scheduler_stops_at_blocking_lock_timeout(monkeypatch, scope):
    connection = SimpleNamespace(execute=AsyncMock(), close=AsyncMock())
    connection.execute.return_value.scalar.return_value = 1
    acquisition = AsyncMock(
        side_effect=[(None, False)] if scope.startswith("metrics:") else [(connection, True), (None, False)]
    )
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
    monkeypatch.setattr(locks, "_acquire_mysql_lock", acquisition)
    persist = AsyncMock()
    evaluate = AsyncMock()
    monkeypatch.setattr(jobs, "persist_metrics", persist)
    monkeypatch.setattr(jobs, "evaluate_alerts", evaluate)
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())

    with pytest.raises(locks.PipelineLockTimeoutError, match=scope):
        run(jobs._persist_runner(AsyncMock(return_value=[]), db, lock_scope="device:central"))

    evaluate.assert_not_awaited()
    if scope.startswith("metrics:"):
        persist.assert_not_awaited()
        db.add.assert_not_called()
        db.commit.assert_not_awaited()
    else:
        persist.assert_awaited_once()
        db.commit.assert_awaited_once()
        connection.close.assert_awaited_once()


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
