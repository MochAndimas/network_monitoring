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


@pytest.mark.parametrize("blocked_scope", ["metrics:device:central", "alerts"])
def test_mysql_scheduler_timeout_stops_protected_work(monkeypatch, blocked_scope):
    """Exercise the actual scheduler path against locks held on another connection."""
    from unittest.mock import AsyncMock, Mock

    from backend.app.scheduler import jobs
    from backend.app.services import pipeline_control

    _require_mysql()
    monkeypatch.setattr(settings, "monitoring_lock_name", f"test.timeout.{uuid.uuid4().hex}")
    monkeypatch.setattr(settings, "monitoring_lock_timeout_seconds", 1)
    persist = AsyncMock()
    evaluate = AsyncMock()
    monkeypatch.setattr(jobs, "persist_metrics", persist)
    monkeypatch.setattr(jobs, "evaluate_alerts", evaluate)
    db = Mock()
    db.commit = AsyncMock()
    run(engine.dispose())

    async def scenario():
        before = pipeline_control.pipeline_lock_health()["contention_count"]
        async with monitoring_pipeline_guard(wait=False, scope=blocked_scope) as acquired:
            assert acquired
            with pytest.raises(pipeline_control.PipelineLockTimeoutError, match=blocked_scope):
                await jobs._persist_runner(AsyncMock(return_value=[]), db, lock_scope="device:central")
            evaluate.assert_not_awaited()
            if blocked_scope.startswith("metrics:"):
                persist.assert_not_awaited()
                db.add.assert_not_called()
                db.commit.assert_not_awaited()
            else:
                persist.assert_awaited_once()
                db.commit.assert_awaited_once()
            # The failed waiter must not release the original owner's lock.
            async with monitoring_pipeline_guard(wait=False, scope=blocked_scope) as acquired_again:
                assert not acquired_again
        async with monitoring_pipeline_guard(wait=True, scope=blocked_scope) as acquired:
            assert acquired
        assert pipeline_control.pipeline_lock_health()["contention_count"] >= before + 1

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_multi_guard_timeout_releases_partial_acquisition(monkeypatch):
    from backend.app.services import pipeline_control

    _require_mysql()
    monkeypatch.setattr(settings, "monitoring_lock_name", f"test.multi.{uuid.uuid4().hex}")
    monkeypatch.setattr(settings, "monitoring_lock_timeout_seconds", 1)
    run(engine.dispose())

    async def scenario():
        async with monitoring_pipeline_guard(wait=False, scope="b") as acquired:
            assert acquired
            with pytest.raises(pipeline_control.PipelineLockTimeoutError):
                async with pipeline_control.monitoring_pipeline_multi_guard(wait=True, scopes=("b", "a")):
                    pytest.fail("Partial ownership must not enter the critical section")
            async with monitoring_pipeline_guard(wait=False, scope="a") as released:
                assert released

    try:
        run(scenario())
    finally:
        run(engine.dispose())


@pytest.mark.parametrize("site", ["", "Branch A"])
def test_mysql_full_cycle_blocks_actual_device_scheduler(monkeypatch, site):
    from unittest.mock import AsyncMock, Mock
    from backend.app.scheduler import jobs
    from backend.app.services import pipeline_control

    _require_mysql()
    monkeypatch.setattr(settings, "collector_agent_site", site)
    monkeypatch.setattr(settings, "monitoring_lock_name", f"test.ownership.{uuid.uuid4().hex}")
    monkeypatch.setattr(settings, "monitoring_lock_timeout_seconds", 1)
    monkeypatch.setattr(jobs, "run_device_checks", AsyncMock(return_value=[]))
    persist = AsyncMock()
    monkeypatch.setattr(jobs, "persist_metrics", persist)

    async def dispatch(name, operation):
        await operation(Mock())

    monkeypatch.setattr(jobs, "_run_scheduler_job", dispatch)
    run(engine.dispose())

    async def scenario():
        async with pipeline_control.monitoring_pipeline_multi_guard(
            wait=False, scopes=pipeline_control.monitoring_full_cycle_lock_scopes()
        ) as acquired:
            assert acquired
            with pytest.raises(pipeline_control.PipelineLockTimeoutError):
                await jobs.run_device_job()
            persist.assert_not_awaited()
            async with monitoring_pipeline_guard(wait=False, scope="metrics:device:site:independent") as other:
                assert other

    try:
        run(scenario())
    finally:
        run(engine.dispose())


@pytest.mark.parametrize("existing_snapshot", [False, True])
def test_mysql_concurrent_snapshot_writers_preserve_latest_and_allow_other_devices(existing_snapshot):
    """A waiting writer must read committed latest state, even with an older read view."""
    import asyncio
    from backend.app.repositories.metric_repository import MetricRepository

    _require_mysql()
    run(engine.dispose())

    async def scenario():
        suffix = uuid.uuid4().hex
        device_ids = []
        now = utcnow().replace(microsecond=0)

        def payload(device_id, at, value="20", status="up"):
            return dict(
                device_id=device_id, metric_name="ping", metric_value=value, status=status, checked_at=at, unit="ms"
            )

        try:
            async with SessionLocal() as db:
                devices = [
                    Device(
                        name=f"snapshot-{suffix}-{i}",
                        ip_address=f"10.198.0.{i + 1}",
                        device_type="switch",
                        site=f"snapshot-{suffix}-{i}",
                        is_active=False,
                    )
                    for i in range(2)
                ]
                db.add_all(devices)
                await db.commit()
                device_ids = [device.id for device in devices]
                if existing_snapshot:
                    await MetricRepository(db).create_metrics([payload(device_ids[0], now - timedelta(minutes=2))])

            async with SessionLocal() as first, SessionLocal() as waiting, SessionLocal() as independent:
                # Open a repeatable-read snapshot and cache an ORM row before the other commit.
                cached_rows = list(
                    (await waiting.scalars(select(LatestMetric).where(LatestMetric.device_id == device_ids[0]))).all()
                )
                await MetricRepository(first).create_metrics([payload(device_ids[0], now)], commit=False)
                started = asyncio.Event()

                async def late_write():
                    started.set()
                    return await MetricRepository(waiting).create_metrics(
                        [payload(device_ids[0], now - timedelta(minutes=1), "timeout", "down")]
                    )

                task = asyncio.create_task(late_write())
                try:
                    await started.wait()
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
                    # The first transaction stays open: another device must still commit.
                    await asyncio.wait_for(
                        MetricRepository(independent).create_metrics([payload(device_ids[1], now)]), timeout=5
                    )
                    await first.commit()
                    await asyncio.wait_for(task, timeout=5)
                    if cached_rows:
                        assert cached_rows[0].checked_at == now
                        assert cached_rows[0].status == "up"
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

            async with SessionLocal() as db:
                row = (await db.scalars(select(LatestMetric).where(LatestMetric.device_id == device_ids[0]))).one()
                assert row.checked_at == now
                assert row.status == "up"
                expected_streak = now - timedelta(minutes=2) if existing_snapshot else now
                assert row.uptime_streak_started_at == expected_streak
                # Old data mixed with a fresh sample must not reset the established streak.
                await MetricRepository(db).create_metrics(
                    [
                        payload(device_ids[0], now - timedelta(minutes=3), "timeout", "down"),
                        payload(device_ids[0], now + timedelta(minutes=1)),
                    ]
                )
                await db.refresh(row)
                assert row.uptime_streak_started_at == expected_streak
                # Equal timestamp uses the higher raw metric ID as the tie-breaker.
                newer = await MetricRepository(db).create_metrics([payload(device_ids[0], row.checked_at, "30")])
                await db.refresh(row)
                assert row.metric_id == newer[0].id
                assert row.metric_value == "30"
        finally:
            if device_ids:
                async with SessionLocal() as db:
                    await db.execute(delete(LatestMetric).where(LatestMetric.device_id.in_(device_ids)))
                    await db.execute(delete(Metric).where(Metric.device_id.in_(device_ids)))
                    await db.execute(delete(Device).where(Device.id.in_(device_ids)))
                    await db.commit()

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_new_snapshot_rolls_back_with_raw_metrics():
    from backend.app.repositories.metric_repository import MetricRepository

    _require_mysql()
    run(engine.dispose())

    async def scenario():
        device_id = None
        try:
            async with SessionLocal() as db:
                device = Device(
                    name=f"rollback-snapshot-{uuid.uuid4().hex}",
                    ip_address="10.198.1.1",
                    device_type="switch",
                    site="snapshot-rollback",
                    is_active=False,
                )
                db.add(device)
                await db.commit()
                device_id = device.id
                with pytest.raises(RuntimeError, match="rollback snapshot"):
                    async with db.begin():
                        await MetricRepository(db).create_metrics(
                            [
                                dict(
                                    device_id=device_id,
                                    metric_name="ping",
                                    metric_value="20",
                                    status="up",
                                    checked_at=utcnow(),
                                    unit="ms",
                                )
                            ],
                            commit=False,
                        )
                        assert (
                            await db.scalar(
                                select(func.count())
                                .select_from(LatestMetric)
                                .where(LatestMetric.device_id == device_id)
                            )
                            == 1
                        )
                        raise RuntimeError("rollback snapshot")
                assert (
                    await db.scalar(
                        select(func.count()).select_from(LatestMetric).where(LatestMetric.device_id == device_id)
                    )
                    == 0
                )
                assert (
                    await db.scalar(select(func.count()).select_from(Metric).where(Metric.device_id == device_id)) == 0
                )
        finally:
            if device_id is not None:
                async with SessionLocal() as db:
                    await db.execute(delete(LatestMetric).where(LatestMetric.device_id == device_id))
                    await db.execute(delete(Metric).where(Metric.device_id == device_id))
                    await db.execute(delete(Device).where(Device.id == device_id))
                    await db.commit()

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_scheduler_owners_from_concurrent_worker_processes():
    import asyncio
    import os
    import sys
    from backend.app.models.scheduler_job_status import SchedulerJobStatus

    _require_mysql()
    run(engine.dispose())
    job_name = f"fixture-owner-{uuid.uuid4().hex}"
    worker_code = """
import asyncio, sys
from backend.app.db.session import SessionLocal, engine
from backend.app.services.observability_service import mark_scheduler_job_failed, mark_scheduler_job_succeeded
async def main():
    try:
        async with SessionLocal() as db:
            if sys.argv[2] == 'fail':
                await mark_scheduler_job_failed(db, job_name=sys.argv[1], duration_ms=1, error='fixture failure')
            else:
                await mark_scheduler_job_succeeded(db, job_name=sys.argv[1], duration_ms=2)
    finally:
        await engine.dispose()
asyncio.run(main())
"""

    async def worker(site, outcome):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            worker_code,
            job_name,
            outcome,
            env={**os.environ, "APP_ENV_FILE": "", "COLLECTOR_AGENT_SITE": site},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == 0, stderr.decode()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def scenario():
        try:
            await asyncio.gather(worker("Branch A", "fail"), worker("Branch A", "fail"), worker("Branch B", "success"))
            async with SessionLocal() as db:
                rows = list(
                    (await db.scalars(select(SchedulerJobStatus).where(SchedulerJobStatus.job_name == job_name))).all()
                )
                assert len(rows) == 2
                by_site = {row.agent_site: row for row in rows}
                assert by_site["Branch A"].consecutive_failures == 2
                assert by_site["Branch B"].consecutive_failures == 0
                assert by_site["Branch B"].last_error is None
        finally:
            async with SessionLocal() as db:
                await db.execute(delete(SchedulerJobStatus).where(SchedulerJobStatus.job_name == job_name))
                await db.commit()

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_outbox_claims_are_exclusive_and_preserve_stream_order():
    import asyncio
    from backend.app.models.notification_outbox import NotificationOutbox as Job
    from backend.app.repositories.notification_outbox_repository import (
        NotificationDraft,
        NotificationOutboxRepository as Repo,
    )

    _require_mysql()
    run(engine.dispose())
    channel = f"fixture-{uuid.uuid4().hex[:12]}"
    now = utcnow().replace(microsecond=750000)

    async def scenario():
        try:
            async with SessionLocal.begin() as db:
                active_id = await Repo(db).enqueue(
                    NotificationDraft(channel + "-active", "device:1", channel, "ACTIVE"), now=now
                )
                resolved_id = await Repo(db).enqueue(
                    NotificationDraft(channel + "-resolved", "device:1", channel, "RESOLVED"), now=now
                )
                other_id = await Repo(db).enqueue(
                    NotificationDraft(channel + "-other", "device:2", channel, "OTHER"), now=now
                )

            async with SessionLocal() as db:
                persisted = await db.get(Job, active_id)
                assert persisted is not None and persisted.available_at == now

            async def claim():
                async with SessionLocal.begin() as db:
                    return await Repo(db).claim_next(channel=channel, now=now, lease_seconds=30, max_attempts=3)

            # Hold the first transaction open to prove the other stream can be
            # claimed while its row lock is still owned by another worker.
            async with SessionLocal.begin() as first_db:
                first = await Repo(first_db).claim_next(channel=channel, now=now, lease_seconds=30, max_attempts=3)
                assert first is not None
                persisted = await first_db.get(Job, first.id)
                assert persisted is not None and persisted.lease_until == now + timedelta(seconds=30)
                second = await asyncio.wait_for(claim(), timeout=5)
                claims = [first, second]
                assert all(item is not None for item in claims)
            assert {item.id for item in claims if item is not None} == {active_id, other_id}
            assert await claim() is None
            async with SessionLocal.begin() as db:
                active = next(item for item in claims if item is not None and item.id == active_id)
                assert await Repo(db).acknowledge(active, now=now, delivered=True, max_attempts=3, retry_seconds=0)
            resolution = await claim()
            assert resolution is not None and resolution.id == resolved_id
        finally:
            async with SessionLocal.begin() as db:
                await db.execute(delete(Job).where(Job.channel == channel))

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_outbox_concurrent_enqueue_is_idempotent_and_rollback_is_atomic():
    import asyncio
    from backend.app.models.notification_outbox import NotificationOutbox as Job
    from backend.app.repositories.notification_outbox_repository import (
        NotificationDraft,
        NotificationOutboxRepository as Repo,
    )

    _require_mysql()
    run(engine.dispose())
    channel = f"fixture-{uuid.uuid4().hex[:12]}"
    payload = NotificationDraft(channel, channel, channel, "fixture")

    async def scenario():
        async def enqueue():
            async with SessionLocal.begin() as db:
                return await Repo(db).enqueue(payload, now=utcnow())

        try:
            ids = await asyncio.gather(enqueue(), enqueue())
            assert ids[0] == ids[1]
            with pytest.raises(RuntimeError, match="rollback"):
                async with SessionLocal.begin() as db:
                    await Repo(db).enqueue(
                        NotificationDraft(channel + "-rollback", channel, channel, "rollback"), now=utcnow()
                    )
                    raise RuntimeError("rollback")
            async with SessionLocal() as db:
                assert await db.scalar(select(func.count()).select_from(Job).where(Job.channel == channel)) == 1
        finally:
            async with SessionLocal.begin() as db:
                await db.execute(delete(Job).where(Job.channel == channel))

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_outbox_delivery_ack_updates_alert_and_incident_atomically():
    from unittest.mock import AsyncMock
    from backend.app.models import Alert, Incident, IncidentTimelineEvent, NotificationOutbox, NotificationOutboxAlert
    from backend.app.repositories.notification_outbox_repository import NotificationDraft
    from backend.app.services.alert_notification_outbox_service import (
        AlertNotificationReference,
        deliver_alert_notification,
        enqueue_alert_notification,
        pending_active_notification_ids,
    )

    _require_mysql()
    run(engine.dispose())

    async def scenario():
        now = utcnow().replace(microsecond=0)
        key = f"fixture-domain-{uuid.uuid4().hex}"
        device_id = None
        job_id = None
        try:
            async with SessionLocal.begin() as db:
                device = Device(
                    name=key, ip_address="10.178.0.1", device_type="switch", site="outbox-fixture", is_active=False
                )
                db.add(device)
                await db.flush()
                device_id = device.id
                alert = Alert(
                    device_id=device_id,
                    alert_type="device_down",
                    severity="critical",
                    message="fixture",
                    status="active",
                    created_at=now,
                )
                incident = Incident(device_id=device_id, summary="fixture", status="active", started_at=now)
                db.add_all([alert, incident])
                await db.flush()
                alert_id = alert.id
                incident_id = incident.id
                job_id = await enqueue_alert_notification(
                    db,
                    NotificationDraft(key, key, "telegram", "fixture"),
                    (AlertNotificationReference(alert_id, "active"),),
                    now=now,
                )
                assert alert.telegram_notified_at is None
                assert await pending_active_notification_ids(db, {alert_id}) == {alert_id}
            # The integration-test database has no operational notification jobs.
            assert (
                await deliver_alert_notification(SessionLocal, AsyncMock(return_value=True), clock=lambda: now)
                == "sent"
            )
            async with SessionLocal() as db:
                stored_alert = await db.get(Alert, alert_id)
                job = await db.get(NotificationOutbox, job_id)
                assert stored_alert is not None and stored_alert.telegram_notified_at == now
                assert job is not None and job.status == "sent"
                assert await pending_active_notification_ids(db, {alert_id}) == set()
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(IncidentTimelineEvent)
                        .where(IncidentTimelineEvent.incident_id == incident_id)
                    )
                    == 1
                )
        finally:
            async with SessionLocal.begin() as db:
                if job_id is not None:
                    await db.execute(delete(NotificationOutboxAlert).where(NotificationOutboxAlert.outbox_id == job_id))
                    await db.execute(delete(NotificationOutbox).where(NotificationOutbox.id == job_id))
                if device_id is not None:
                    ids = select(Incident.id).where(Incident.device_id == device_id)
                    await db.execute(delete(IncidentTimelineEvent).where(IncidentTimelineEvent.incident_id.in_(ids)))
                    await db.execute(delete(Incident).where(Incident.device_id == device_id))
                    await db.execute(delete(Alert).where(Alert.device_id == device_id))
                    await db.execute(delete(Device).where(Device.id == device_id))

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_legacy_index_reconciliation_preserves_data_and_constraints():
    """Exercise real legacy drift, an interrupted DDL run, and a clean rerun."""
    from pathlib import Path
    import runpy
    from unittest.mock import patch

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError

    from backend.app.db.base import Base

    _require_mysql()
    migration = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "alembic/versions/20260908_0028_reconcile_legacy_indexes.py")
    )
    sync_engine = create_engine(settings.database_url)
    fixture_key = "reconcile-fixture-" + uuid.uuid4().hex
    try:
        with sync_engine.connect() as db:
            context = MigrationContext.configure(db)
            with Operations.context(context):
                migration["upgrade"]()  # Already canonical is a no-op.
                assert compare_metadata(context, Base.metadata) == []
                db.execute(text("INSERT INTO thresholds (`key`, value) VALUES (:key, 17)"), {"key": fixture_key})
                db.commit()
                foreign_keys = {
                    table: inspect(db).get_foreign_keys(table)
                    for table in (
                        "latest_metrics",
                        "incident_timeline_events",
                        "maintenance_windows",
                        "threshold_overrides",
                    )
                }
                # Reproduce the operational schema: old unique index names,
                # redundant FK indexes, and missing rollup lookup indexes.
                for table, name, columns in migration["_REDUNDANT"]:
                    Operations(context).create_index(name, table, list(columns))
                for table, name, columns in migration["_REPLACED"]:
                    Operations(context).drop_index(name, table_name=table)
                    Operations(context).create_index(name, table, list(columns), unique=True)
                for table, name, _, _ in migration["_REQUIRED"]:
                    Operations(context).drop_index(name, table_name=table)
                db.commit()
                # MySQL DDL survives failure. Retry must recognize completed work.
                with patch("alembic.op.drop_index", side_effect=RuntimeError("fixture interruption")):
                    with pytest.raises(RuntimeError, match="fixture interruption"):
                        migration["upgrade"]()
                migration["upgrade"]()
                migration["upgrade"]()
                assert compare_metadata(context, Base.metadata) == []
                assert db.scalar(text("SELECT value FROM thresholds WHERE `key`=:key"), {"key": fixture_key}) == 17
                for table, expected in foreign_keys.items():
                    assert inspect(db).get_foreign_keys(table) == expected
                db.commit()
                with pytest.raises(IntegrityError):
                    db.execute(text("INSERT INTO thresholds (`key`, value) VALUES (:key, 99)"), {"key": fixture_key})
                db.rollback()
                migration["downgrade"]()
                assert compare_metadata(context, Base.metadata) == []
                # Unexpected known-name definitions must fail before changing indexes.
                table, name, _ = migration["_REDUNDANT"][0]
                Operations(context).create_index(name, table, ["username"])
                try:
                    with pytest.raises(RuntimeError, match="Unexpected definition"):
                        migration["upgrade"]()
                    assert name in {item["name"] for item in inspect(db).get_indexes(table)}
                finally:
                    assert isinstance(name, str)
                    Operations(context).drop_index(name, table_name=table)
                db.execute(text("DELETE FROM thresholds WHERE `key`=:key"), {"key": fixture_key})
                db.commit()
    finally:
        sync_engine.dispose()


def test_mysql_outbox_producers_serialize_one_stream_without_blocking_others():
    import asyncio
    from backend.app.models import NotificationOutbox, NotificationOutboxStream
    from backend.app.repositories.notification_outbox_repository import NotificationDraft, NotificationOutboxRepository

    _require_mysql()
    run(engine.dispose())

    async def scenario():
        key = "producer-fixture-" + uuid.uuid4().hex
        now = utcnow()
        waiting = asyncio.Event()
        task = None

        async def next_producer():
            async with SessionLocal.begin() as db:
                waiting.set()
                return await NotificationOutboxRepository(db).enqueue(
                    NotificationDraft(key + "-second", key, "telegram", "RESOLVED", "123"), now=now
                )

        try:
            async with SessionLocal.begin() as first:
                first_id = await NotificationOutboxRepository(first).enqueue(
                    NotificationDraft(key + "-first", key, "telegram", "ACTIVE", "123"), now=now
                )
                task = asyncio.create_task(next_producer())
                await waiting.wait()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
                async with SessionLocal.begin() as other:
                    await asyncio.wait_for(
                        NotificationOutboxRepository(other).enqueue(
                            NotificationDraft(key + "-other", key + "-other", "telegram", "OTHER", "456"), now=now
                        ),
                        timeout=5,
                    )
                assert not task.done()
            second_id = await asyncio.wait_for(task, timeout=5)
            assert first_id < second_id
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            async with SessionLocal.begin() as db:
                await db.execute(
                    delete(NotificationOutbox).where(NotificationOutbox.stream_key.in_([key, key + "-other"]))
                )
                await db.execute(
                    delete(NotificationOutboxStream).where(
                        NotificationOutboxStream.stream_key.in_([key, key + "-other"])
                    )
                )

    try:
        run(scenario())
    finally:
        run(engine.dispose())


def test_mysql_evaluator_and_delivery_ack_share_domain_first_lock_order(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from backend.app.alerting.engine import evaluate_alerts
    from backend.app.alerting.engine_parts import impl
    from backend.app.models import (
        Alert,
        Incident,
        IncidentTimelineEvent,
        NotificationOutbox,
        NotificationOutboxAlert,
        NotificationOutboxStream,
    )
    from backend.app.services import alert_notification_outbox_service as delivery
    from backend.app.services.telegram_outbox_writer import TelegramOutboxWriter

    _require_mysql()
    run(engine.dispose())
    monkeypatch.setattr(impl, "_expected_alert_map", AsyncMock(return_value={}))
    original_lock = delivery.lock_alert_notification_state

    async def scenario():
        key = "ack-contention-" + uuid.uuid4().hex
        writer = TelegramOutboxWriter("123")
        waiting = asyncio.Event()
        device_id = None
        stream = None
        task = None

        async def observed_lock(db, ids):
            waiting.set()
            return await original_lock(db, ids)

        monkeypatch.setattr(delivery, "lock_alert_notification_state", observed_lock)
        try:
            async with SessionLocal.begin() as db:
                device = Device(name=key, ip_address="10.174.0.1", device_type="switch", site=key)
                db.add(device)
                await db.flush()
                device_id = device.id
                alert = Alert(
                    device_id=device_id,
                    alert_type="device_down",
                    status="active",
                    severity="critical",
                    message="fixture",
                    created_at=utcnow() - timedelta(hours=1),
                )
                db.add(alert)
                await db.flush()
                alert_id = alert.id
                await writer(
                    db,
                    [
                        dict(
                            alert=alert,
                            alert_id=alert_id,
                            action="active",
                            device=device,
                            alert_type=alert.alert_type,
                            severity=alert.severity,
                            message=alert.message,
                        )
                    ],
                )
                stream = await db.scalar(
                    select(NotificationOutbox.stream_key)
                    .join(NotificationOutboxAlert)
                    .where(NotificationOutboxAlert.alert_id == alert_id)
                )

            async def enqueue_while_ack_waits(db, events):
                nonlocal task
                assert events and events[0]["action"] == "resolved"
                task = asyncio.create_task(
                    delivery.deliver_alert_notification(
                        SessionLocal, AsyncMock(), routed_sender=AsyncMock(return_value=True)
                    )
                )
                await asyncio.wait_for(waiting.wait(), timeout=5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
                # Worker must not hold the job row while waiting for this alert.
                await asyncio.wait_for(writer(db, events), timeout=5)

            async with SessionLocal.begin() as db:
                await evaluate_alerts(db, commit=False, notification_writer=enqueue_while_ack_waits)
            assert task is not None
            assert await asyncio.wait_for(task, timeout=5) == "sent"
            assert (
                await delivery.deliver_alert_notification(
                    SessionLocal, AsyncMock(), routed_sender=AsyncMock(return_value=True)
                )
                == "sent"
            )
            async with SessionLocal() as db:
                stored = await db.get(Alert, alert_id)
                assert stored is not None and stored.status == "resolved" and stored.telegram_notified_at is not None
                assert (
                    await db.scalars(select(NotificationOutbox.status).where(NotificationOutbox.stream_key == stream))
                ).all() == ["sent", "sent"]
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            async with SessionLocal.begin() as db:
                if stream is not None:
                    jobs = select(NotificationOutbox.id).where(NotificationOutbox.stream_key == stream)
                    await db.execute(delete(NotificationOutboxAlert).where(NotificationOutboxAlert.outbox_id.in_(jobs)))
                    await db.execute(delete(NotificationOutbox).where(NotificationOutbox.stream_key == stream))
                    await db.execute(
                        delete(NotificationOutboxStream).where(NotificationOutboxStream.stream_key == stream)
                    )
                if device_id is not None:
                    incidents = select(Incident.id).where(Incident.device_id == device_id)
                    await db.execute(
                        delete(IncidentTimelineEvent).where(IncidentTimelineEvent.incident_id.in_(incidents))
                    )
                    await db.execute(delete(Incident).where(Incident.device_id == device_id))
                    await db.execute(delete(Alert).where(Alert.device_id == device_id))
                    await db.execute(delete(Device).where(Device.id == device_id))

    try:
        run(scenario())
    finally:
        run(engine.dispose())
