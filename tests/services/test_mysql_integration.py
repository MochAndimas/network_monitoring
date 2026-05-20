"""Define test module behavior for `tests/services/test_mysql_integration.py`.

This module contains automated regression and validation scenarios.
"""

from __future__ import annotations

from datetime import timedelta
import uuid

import pytest
from sqlalchemy import delete, func, select

from backend.app.core.config import settings
from backend.app.core.time import utcnow
from backend.app.db.session import SessionLocal, engine
from backend.app.models.device import Device
from backend.app.models.latest_metric import LatestMetric
from backend.app.models.metric import Metric
from backend.app.models.metric_cold_archive import MetricColdArchive
from backend.app.models.metric_daily_rollup import MetricDailyRollup
from backend.app.models.retention_bucket_progress import RetentionBucketProgress
from backend.app.services.pipeline_control import monitoring_pipeline_guard
from backend.app.services.retention_service import cleanup_monitoring_data
from tests.test_utils import run


def _require_mysql() -> None:
    if engine.dialect.name != "mysql":
        pytest.skip("MySQL integration tests require mysql dialect")
    try:
        import greenlet  # noqa: F401
    except Exception:  # pragma: no cover - environment specific hardening
        pytest.skip("MySQL integration tests require greenlet runtime support")


async def _delete_mysql_retention_fixture(unique_suffix: str) -> None:
    """Delete the retention integration-test fixture if a failed test left it behind."""
    device_name = f"MySQL Retention Device {unique_suffix}"
    async with SessionLocal() as db:
        device_ids = list(
            (
                await db.scalars(
                    select(Device.id).where(
                        Device.name == device_name,
                        Device.site == "integration",
                        Device.description == "mysql retention integration test",
                    )
                )
            ).all()
        )
        if not device_ids:
            return
        await db.execute(delete(LatestMetric).where(LatestMetric.device_id.in_(device_ids)))
        await db.execute(delete(Metric).where(Metric.device_id.in_(device_ids)))
        await db.execute(delete(MetricDailyRollup).where(MetricDailyRollup.device_id.in_(device_ids)))
        await db.execute(delete(MetricColdArchive).where(MetricColdArchive.device_id.in_(device_ids)))
        await db.execute(delete(RetentionBucketProgress).where(RetentionBucketProgress.device_id.in_(device_ids)))
        await db.execute(delete(Device).where(Device.id.in_(device_ids)))
        await db.commit()


def test_mysql_monitoring_pipeline_guard_is_exclusive_for_nonblocking_acquire():
    _require_mysql()

    original_lock_name = settings.monitoring_lock_name
    settings.monitoring_lock_name = f"network_monitoring.test.lock.{uuid.uuid4().hex}"
    run(engine.dispose())

    async def scenario() -> None:
        async with monitoring_pipeline_guard(wait=False) as first_acquired:
            assert first_acquired is True
            async with monitoring_pipeline_guard(wait=False) as second_acquired:
                assert second_acquired is False

    try:
        run(scenario())
    finally:
        settings.monitoring_lock_name = original_lock_name
        run(engine.dispose())


def test_mysql_monitoring_pipeline_guard_allows_independent_scopes():
    _require_mysql()

    original_lock_name = settings.monitoring_lock_name
    settings.monitoring_lock_name = f"network_monitoring.test.lock.{uuid.uuid4().hex}"
    run(engine.dispose())

    async def scenario() -> None:
        async with monitoring_pipeline_guard(wait=False, scope="metrics:internet") as first_acquired:
            assert first_acquired is True
            async with monitoring_pipeline_guard(wait=False, scope="metrics:internet") as same_scope_acquired:
                assert same_scope_acquired is False
            async with monitoring_pipeline_guard(wait=False, scope="metrics:server") as other_scope_acquired:
                assert other_scope_acquired is True

    try:
        run(scenario())
    finally:
        settings.monitoring_lock_name = original_lock_name
        run(engine.dispose())


def test_mysql_cleanup_monitoring_data_rolls_back_when_transaction_fails():
    _require_mysql()

    original_lock_name = settings.monitoring_lock_name
    settings.monitoring_lock_name = f"network_monitoring.test.lock.{uuid.uuid4().hex}"
    run(engine.dispose())

    async def scenario() -> None:
        unique_suffix = utcnow().strftime("%Y%m%d%H%M%S%f")
        metric_id: int
        try:
            async with SessionLocal() as db:
                device = Device(
                    name=f"MySQL Retention Device {unique_suffix}",
                    ip_address=f"10.199.{int(unique_suffix[-4:-2])}.{int(unique_suffix[-2:]) or 1}",
                    device_type="server",
                    site="integration",
                    description="mysql retention integration test",
                    is_active=False,
                )
                db.add(device)
                await db.flush()
                old_metric = Metric(
                    device_id=device.id,
                    metric_name="ping",
                    metric_value="123.45",
                    metric_value_numeric=123.45,
                    status="up",
                    unit="ms",
                    checked_at=utcnow() - timedelta(days=max(settings.raw_metric_retention_days, 1) + 3),
                )
                db.add(old_metric)
                await db.commit()
                metric_id = int(old_metric.id)

            async with SessionLocal() as db:
                baseline_rollup_rows = int(await db.scalar(select(func.count()).select_from(MetricDailyRollup)) or 0)
                baseline_archive_rows = int(await db.scalar(select(func.count()).select_from(MetricColdArchive)) or 0)
                await db.rollback()
                try:
                    async with db.begin():
                        await cleanup_monitoring_data(db, commit=False)
                        raise RuntimeError("force rollback")
                except RuntimeError:
                    pass

                remaining_metric = int(
                    await db.scalar(select(func.count()).select_from(Metric).where(Metric.id == metric_id)) or 0
                )
                rollup_rows = int(await db.scalar(select(func.count()).select_from(MetricDailyRollup)) or 0)
                archive_rows = int(await db.scalar(select(func.count()).select_from(MetricColdArchive)) or 0)

                assert remaining_metric == 1
                assert rollup_rows == baseline_rollup_rows
                assert archive_rows == baseline_archive_rows
        finally:
            await _delete_mysql_retention_fixture(unique_suffix)

    try:
        run(scenario())
    finally:
        settings.monitoring_lock_name = original_lock_name
        run(engine.dispose())
