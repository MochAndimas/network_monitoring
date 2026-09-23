"""Scheduler and manual collectors must share ownership and actual lock scopes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app.core.config import settings
from backend.app.scheduler import jobs
from backend.app.services import pipeline_control as locks, run_cycle_service as cycles
from backend.app.services.collector_ownership import DeviceCollectorOwnership
from tests.test_utils import run


@pytest.mark.parametrize("site", ["", "Branch A", "central", "Branch/A"])
def test_scheduler_and_manual_collection_share_site_filters(monkeypatch, site):
    monkeypatch.setattr(settings, "collector_agent_site", site)
    monkeypatch.setattr(settings, "collector_agent_sites", "Branch A, Branch B")
    collector = AsyncMock(return_value=[])
    monkeypatch.setattr(jobs, "run_device_checks", collector)
    monkeypatch.setattr(cycles, "run_device_checks", collector)

    async def dispatch(name, operation):
        await operation(Mock())

    async def persist(runner, db, **kwargs):
        await runner(db)

    monkeypatch.setattr(jobs, "_run_scheduler_job", dispatch)
    monkeypatch.setattr(jobs, "_persist_runner", persist)

    async def scenario():
        await jobs.run_device_job()
        await cycles._run_owned_device_checks(Mock())

    run(scenario())
    expected = {"site": site or None, "excluded_sites": set() if site else {"Branch A", "Branch B"}}
    assert [call.kwargs for call in collector.await_args_list] == [expected, expected]


def test_site_lock_names_do_not_alias_central_or_normalized_names():
    owners = [None, "central", "Branch/A", "Branch A", "東京"]
    scopes = {DeviceCollectorOwnership(site, frozenset()).lock_scope for site in owners}
    assert len(scopes) == len(owners)


@pytest.mark.parametrize("site", ["", "Branch A"])
def test_manual_guard_blocks_actual_scheduler_writer(monkeypatch, site):
    monkeypatch.setattr(settings, "collector_agent_site", site)
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setattr(locks, "_monitoring_pipeline_locks", {})
    monkeypatch.setattr(locks, "_lock_timeout_seconds", lambda **kwargs: 0.01)
    monkeypatch.setattr(jobs, "run_device_checks", AsyncMock(return_value=[]))
    persist = AsyncMock()
    monkeypatch.setattr(jobs, "persist_metrics", persist)

    async def dispatch(name, operation):
        await operation(Mock())

    monkeypatch.setattr(jobs, "_run_scheduler_job", dispatch)

    async def scenario():
        async with locks.monitoring_pipeline_multi_guard(
            wait=False, scopes=locks.monitoring_full_cycle_lock_scopes()
        ) as acquired:
            assert acquired
            with pytest.raises(locks.PipelineLockTimeoutError):
                await jobs.run_device_job()
            persist.assert_not_awaited()
            other = DeviceCollectorOwnership("Independent", frozenset())
            async with locks.monitoring_pipeline_guard(wait=False, scope=f"metrics:{other.lock_scope}") as independent:
                assert independent

    run(scenario())


@pytest.mark.parametrize("site, count", [("", 4), ("Branch A", 1)])
def test_manual_cycle_runs_only_domains_owned_by_process(monkeypatch, site, count):
    monkeypatch.setattr(settings, "collector_agent_site", site)
    runners = cycles._monitor_runners()
    assert len(runners) == count
    assert cycles._run_owned_device_checks in runners
    scopes = locks.monitoring_full_cycle_lock_scopes()
    assert ("metrics:internet" in scopes) == (not site)


@pytest.mark.parametrize("site", ["", "Branch A"])
def test_run_cycle_endpoint_rejects_during_actual_scheduler_write(monkeypatch, site):
    import asyncio
    from fastapi import HTTPException, Request
    from backend.app.api.routes import system

    monkeypatch.setattr(settings, "collector_agent_site", site)
    monkeypatch.setattr(locks, "engine", SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    monkeypatch.setattr(locks, "_monitoring_pipeline_locks", {})
    monkeypatch.setattr(jobs, "run_device_checks", AsyncMock(return_value=[]))
    monkeypatch.setattr(jobs, "evaluate_alerts", AsyncMock(return_value=[]))
    db = Mock()
    db.commit = AsyncMock()

    async def dispatch(name, operation):
        await operation(db)

    monkeypatch.setattr(jobs, "_run_scheduler_job", dispatch)

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold_write(*args, **kwargs):
            entered.set()
            await release.wait()

        monkeypatch.setattr(jobs, "persist_metrics", hold_write)
        task = asyncio.create_task(jobs.run_device_job())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(HTTPException) as error:
                await system.run_cycle(Request({"type": "http"}), actor=Mock(), db=Mock())
            assert error.value.status_code == 409
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=2)

    run(scenario())
