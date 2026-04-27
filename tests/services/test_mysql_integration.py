"""Define test module behavior for `tests/services/test_mysql_integration.py`.

This module contains automated regression and validation scenarios.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from backend.app.core.config import settings
from backend.app.core.time import utcnow
from backend.app.db.session import SessionLocal, engine
from backend.app.models.device import Device
from backend.app.models.metric import Metric
from backend.app.models.metric_cold_archive import MetricColdArchive
from backend.app.models.metric_daily_rollup import MetricDailyRollup
from backend.app.services.pipeline_control import monitoring_pipeline_guard
from backend.app.services.retention_service import cleanup_monitoring_data
from tests.test_utils import run


def _require_mysql() -> None:
    """Perform require mysql.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    if engine.dialect.name != "mysql":
        pytest.skip("MySQL integration tests require mysql dialect")
    try:
        import greenlet  # noqa: F401
    except Exception:  # pragma: no cover - environment specific hardening
        pytest.skip("MySQL integration tests require greenlet runtime support")


def test_mysql_monitoring_pipeline_guard_is_exclusive_for_nonblocking_acquire():
    """Validate that mysql monitoring pipeline guard is exclusive for nonblocking acquire.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    _require_mysql()

    async def scenario() -> None:
        async with monitoring_pipeline_guard(wait=False) as first_acquired:
            assert first_acquired is True
            async with monitoring_pipeline_guard(wait=False) as second_acquired:
                assert second_acquired is False

    run(scenario())


def test_mysql_cleanup_monitoring_data_rolls_back_when_transaction_fails():
    """Validate that mysql cleanup monitoring data rolls back when transaction fails.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    _require_mysql()

    async def scenario() -> None:
        unique_suffix = utcnow().strftime("%Y%m%d%H%M%S%f")
        metric_id: int

        async with SessionLocal() as db:
            device = Device(
                name=f"MySQL Retention Device {unique_suffix}",
                ip_address=f"10.199.{int(unique_suffix[-4:-2])}.{int(unique_suffix[-2:]) or 1}",
                device_type="server",
                site="integration",
                description="mysql retention integration test",
                is_active=True,
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
            assert rollup_rows == 0
            assert archive_rows == 0

            await db.execute(Metric.__table__.delete().where(Metric.id == metric_id))
            await db.execute(Device.__table__.delete().where(Device.name == f"MySQL Retention Device {unique_suffix}"))
            await db.commit()

    run(scenario())
