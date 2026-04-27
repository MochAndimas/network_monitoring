"""Define test module behavior for `tests/services/test_transaction_boundary.py`.

This module contains automated regression and validation scenarios.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.models.metric import Metric
from backend.app.models.scheduler_job_status import SchedulerJobStatus
from backend.app.models.threshold import Threshold
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.services import run_cycle_service
from backend.app.scheduler import jobs as scheduler_jobs
from backend.app.core.time import utcnow
from tests.test_utils import create_all, drop_all, run


def test_run_monitoring_cycle_rolls_back_metrics_when_alerting_fails(monkeypatch):
    """Validate that run monitoring cycle rolls back metrics when alerting fails.

    Args:
        monkeypatch: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    async def fake_collect_monitoring_metrics():
        return [
            {
                "device_id": 1,
                "metric_name": "ping",
                "metric_value": "12.34",
                "status": "up",
                "unit": "ms",
                "checked_at": utcnow(),
            }
        ]

    async def fake_evaluate_alerts(_db, *, commit: bool = True):
        raise RuntimeError("forced-alerting-failure")

    monkeypatch.setattr(run_cycle_service, "collect_monitoring_metrics", fake_collect_monitoring_metrics)
    monkeypatch.setattr(run_cycle_service, "evaluate_alerts", fake_evaluate_alerts)

    async def scenario():
        async with session_factory() as db:
            await DeviceRepository(db).upsert_devices(
                [{"name": "Gateway", "ip_address": "192.168.1.1", "device_type": "internet_target"}]
            )
            with pytest.raises(RuntimeError, match="forced-alerting-failure"):
                await run_cycle_service.run_monitoring_cycle(db)

            metric_count = int(await db.scalar(select(func.count()).select_from(Metric)) or 0)
            return metric_count

    try:
        metric_count = run(scenario())
        assert metric_count == 0
    finally:
        run(drop_all(engine))


def test_scheduler_job_failure_rolls_back_domain_writes_and_updates_job_status(monkeypatch):
    """Validate that scheduler job failure rolls back domain writes and updates job status.

    Args:
        monkeypatch: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False,
        },
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))
    monkeypatch.setattr(scheduler_jobs, "SessionLocal", session_factory)

    async def failing_operation(db):
        db.add(
            Threshold(
                key="phase2_atomic_threshold",
                value=1.0,
                description="must rollback on failure",
            )
        )
        await db.flush()
        raise RuntimeError("forced-job-failure")

    async def scenario():
        with pytest.raises(RuntimeError, match="forced-job-failure"):
            await scheduler_jobs._run_scheduler_job("phase2_atomic_job", failing_operation)

        async with session_factory() as db:
            threshold = await db.scalar(
                select(Threshold).where(Threshold.key == "phase2_atomic_threshold")
            )
            job_status = await db.scalar(
                select(SchedulerJobStatus).where(SchedulerJobStatus.job_name == "phase2_atomic_job")
            )
            return threshold, job_status

    try:
        threshold, job_status = run(scenario())
        assert threshold is None
        assert job_status is not None
        assert job_status.is_running is False
        assert job_status.consecutive_failures == 1
        assert job_status.last_failed_at is not None
        assert "forced-job-failure" in str(job_status.last_error or "")
    finally:
        run(drop_all(engine))
