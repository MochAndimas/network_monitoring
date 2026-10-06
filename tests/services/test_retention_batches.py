"""Retention failure/retry contracts and bounded work, independent of facade globals."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.core.time import utcnow
from backend.app.models.device import Device
from backend.app.models.metric import Metric
from backend.app.models.latest_metric import LatestMetric
from backend.app.models.metric_daily_rollup import MetricDailyRollup
from backend.app.models.metric_cold_archive import MetricColdArchive
from backend.app.models.retention_bucket_progress import RetentionBucketProgress
from backend.app.models.metric_site_type_daily_summary import MetricSiteTypeDailySummary
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.services import retention_service
from backend.app.services.retention_service import (
    cleanup_monitoring_data,
    delete_expired_raw_metrics,
    rollup_completed_raw_metrics,
)
from tests.test_utils import create_all, drop_all, run


@pytest.fixture
def retention_fixture(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    run(create_all(engine))
    monkeypatch.setattr(settings, "retention_source_batch_size", 2)
    monkeypatch.setattr(settings, "retention_delete_batch_size", 2)
    monkeypatch.setattr(settings, "retention_max_batches_per_phase", 20)
    monkeypatch.setattr(settings, "raw_metric_retention_days", 7)
    try:
        yield engine, sessions
    finally:
        run(drop_all(engine))


async def seed(sessions, count=9):
    async with sessions() as db:
        device = Device(name="Retention fixture", ip_address="192.0.2.1", device_type="voip", site="A")
        db.add(device)
        await db.commit()
        device_id = device.id
        old = utcnow() - timedelta(days=10)
        await MetricRepository(db).create_metrics(
            [
                dict(
                    device_id=device_id,
                    metric_name="ping",
                    metric_value=str(i),
                    status="up",
                    unit="ms",
                    checked_at=old + timedelta(seconds=i),
                )
                for i in range(count)
            ]
        )
        return device_id, old


async def assert_complete(sessions, count):
    async with sessions() as db:
        assert (await db.scalars(select(MetricDailyRollup))).one().total_samples == count
        archive = (await db.scalars(select(MetricColdArchive))).one()
        assert archive.sample_count == count
        assert archive.avg_numeric_value == (count - 1) / 2
        remaining = (await db.scalars(select(Metric))).all()
        assert len(remaining) == 1
        latest = (await db.scalars(select(LatestMetric))).one()
        assert remaining[0].id == latest.metric_id
        assert archive.last_metric_value == str(count - 1)


def test_backlog_respects_run_budget_and_resumes(retention_fixture, monkeypatch):
    engine, sessions = retention_fixture
    monkeypatch.setattr(settings, "retention_max_batches_per_phase", 2)
    selected_sizes = []
    original = retention_service.RetentionRepository.source_batch

    async def capture(self, *args):
        ids = await original(self, *args)
        selected_sizes.append(len(ids))
        return ids

    monkeypatch.setattr(retention_service.RetentionRepository, "source_batch", capture)

    async def scenario():
        await seed(sessions, 11)
        async with sessions() as db:
            first = await cleanup_monitoring_data(db)
            assert first["deleted_metrics"] == 4
            assert (await db.scalars(select(MetricDailyRollup))).one().total_samples == 4
            assert await db.scalar(select(func.count()).select_from(Metric)) == 7
        for _ in range(3):
            async with sessions() as db:
                await cleanup_monitoring_data(db)
        await assert_complete(sessions, 11)
        assert max(selected_sizes) == 2
        async with sessions() as db:
            result = await cleanup_monitoring_data(db)
            assert result["rolled_up_days"] == result["archived_metric_groups"] == result["deleted_metrics"] == 0

    run(scenario())


@pytest.mark.parametrize("stage", ["rollup", "archive", "delete", "summary"])
def test_failure_keeps_completed_batches_and_retry_is_idempotent(retention_fixture, monkeypatch, stage):
    _, sessions = retention_fixture
    target = {
        "rollup": "_upsert_rollup_payloads",
        "archive": "_upsert_archive_payloads",
        "delete": "delete_raw_batch",
        "summary": "refresh_site_type_daily_summaries",
    }[stage]
    owner = (
        retention_service
        if stage in {"rollup", "archive"}
        else (retention_service.RetentionRepository if stage == "delete" else MetricRepository)
    )
    original = getattr(owner, target)
    calls = 0

    async def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await original(*args, **kwargs)
        if calls == (1 if stage == "summary" else 2):
            raise RuntimeError("interrupted after writes before commit")
        return result

    monkeypatch.setattr(owner, target, fail)

    async def scenario():
        await seed(sessions)
        async with sessions() as db:
            with pytest.raises(RuntimeError, match="interrupted"):
                await cleanup_monitoring_data(db)
        async with sessions() as db:
            if stage == "rollup":
                assert (await db.scalars(select(MetricDailyRollup))).one().total_samples == 2
            if stage == "archive":
                assert (await db.scalars(select(MetricColdArchive))).one().sample_count == 2
            if stage == "delete":
                assert await db.scalar(select(func.count()).select_from(Metric)) == 7
            if stage == "summary":
                marker = await db.scalar(
                    select(RetentionBucketProgress).where(RetentionBucketProgress.bucket_kind == "summary")
                )
                assert marker.source_max_metric_id is None
                assert await db.scalar(select(func.count()).select_from(MetricSiteTypeDailySummary)) == 0
        monkeypatch.setattr(owner, target, original)
        async with sessions() as db:
            await cleanup_monitoring_data(db)
            await cleanup_monitoring_data(db)
        await assert_complete(sessions, 9)

    run(scenario())


def test_delete_requires_both_checkpoints_and_existing_aggregates(retention_fixture):
    _, sessions = retention_fixture

    async def scenario():
        await seed(sessions)
        async with sessions() as db:
            assert await delete_expired_raw_metrics(db) == 0
            await rollup_completed_raw_metrics(db)
            assert await delete_expired_raw_metrics(db) == 0
            await retention_service.archive_expired_raw_metrics(db)
            await db.execute(delete(MetricColdArchive))
            await db.commit()
            assert await delete_expired_raw_metrics(db) == 0
            await MetricRepository(db).create_metrics(
                [
                    dict(
                        device_id=1,
                        metric_name="ping",
                        metric_value="99",
                        status="up",
                        unit="ms",
                        checked_at=utcnow() - timedelta(days=10),
                    )
                ]
            )
            with pytest.raises(ValueError, match="checkpoint has no aggregate"):
                await cleanup_monitoring_data(db)

    run(scenario())


def test_caller_owned_mode_rolls_back_every_stage(retention_fixture):
    _, sessions = retention_fixture

    async def scenario():
        await seed(sessions)
        async with sessions() as db:
            with pytest.raises(RuntimeError):
                async with db.begin():
                    await cleanup_monitoring_data(db, commit=False)
                    raise RuntimeError("abort")
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Metric)) == 9
            assert await db.scalar(select(func.count()).select_from(MetricDailyRollup)) == 0
            assert await db.scalar(select(func.count()).select_from(RetentionBucketProgress)) == 0

    run(scenario())


def test_late_metrics_merge_after_partial_prune_with_equal_timestamp(retention_fixture):
    _, sessions = retention_fixture

    async def scenario():
        device_id, old = await seed(sessions, 3)
        async with sessions() as db:
            await cleanup_monitoring_data(db)
            # Higher ID with the same checked_at must win the last-value tie.
            await MetricRepository(db).create_metrics(
                [
                    dict(
                        device_id=device_id,
                        metric_name="ping",
                        metric_value="10",
                        status="up",
                        unit="ms",
                        checked_at=old + timedelta(seconds=2),
                    )
                ]
            )
            await cleanup_monitoring_data(db)
            await cleanup_monitoring_data(db)
            rollup = (await db.scalars(select(MetricDailyRollup))).one()
            archive = (await db.scalars(select(MetricColdArchive))).one()
            assert rollup.total_samples == archive.sample_count == 4
            assert archive.avg_numeric_value == 3.25
            assert archive.last_metric_value == "10"
            assert await db.scalar(select(func.count()).select_from(Metric)) == 1

    run(scenario())


def test_legacy_fingerprint_requires_explicit_rebuild(retention_fixture):
    _, sessions = retention_fixture

    async def scenario():
        device_id, old = await seed(sessions, 2)
        async with sessions() as db:
            db.add(MetricDailyRollup(device_id=device_id, rollup_date=old.date(), total_samples=100))
            await db.commit()
            with pytest.raises(ValueError, match="no source checkpoint"):
                await cleanup_monitoring_data(db)
            assert await db.scalar(select(func.count()).select_from(Metric)) == 2

    run(scenario())


def test_summary_groups_are_paged_and_reconcile_device_metadata(retention_fixture, monkeypatch):
    _, sessions = retention_fixture
    monkeypatch.setattr(settings, "retention_rollup_batch_size", 1)
    monkeypatch.setattr(settings, "retention_max_batches_per_phase", 1)

    async def scenario():
        await seed(sessions, 1)
        async with sessions() as db:
            device = Device(name="Second", ip_address="192.0.2.2", device_type="voip", site="B")
            db.add(device)
            await db.commit()
            await MetricRepository(db).create_metrics(
                [
                    dict(
                        device_id=device.id,
                        metric_name="ping",
                        metric_value="1",
                        status="up",
                        unit="ms",
                        checked_at=utcnow() - timedelta(days=10),
                    )
                ]
            )
            for _ in range(4):
                await cleanup_monitoring_data(db)
            summaries = (await db.scalars(select(MetricSiteTypeDailySummary))).all()
            assert {row.site for row in summaries} == {"A", "B"}
            device.site = "A"
            await db.commit()
            for _ in range(3):
                await cleanup_monitoring_data(db)
            summaries = (await db.scalars(select(MetricSiteTypeDailySummary))).all()
            assert len(summaries) == 1
            assert summaries[0].site == "A"
            assert summaries[0].device_count == 2

    run(scenario())


def test_other_retention_tables_use_bounded_delete_batches(retention_fixture, monkeypatch):
    from backend.app.models.collector_run import CollectorRun
    from backend.app.models.alert import Alert
    from backend.app.models.incident import Incident

    _, sessions = retention_fixture
    monkeypatch.setattr(settings, "retention_max_batches_per_phase", 1)

    async def scenario():
        async with sessions() as db:
            old = utcnow() - timedelta(days=200)
            db.add_all(
                [CollectorRun(collector_name="fixture", status="ok", duration_ms=1, checked_at=old) for _ in range(5)]
            )
            db.add_all(
                [
                    Alert(
                        alert_type="fixture",
                        severity="warning",
                        message="fixture",
                        status="resolved",
                        created_at=old,
                        resolved_at=old,
                    )
                    for _ in range(5)
                ]
            )
            db.add_all([Incident(summary="fixture", status="resolved", started_at=old, ended_at=old) for _ in range(5)])
            db.add(
                Alert(
                    alert_type="fixture-active", severity="warning", message="active", status="active", created_at=old
                )
            )
            await db.commit()
            result = await cleanup_monitoring_data(db)
            assert result["deleted_collector_runs"] == result["deleted_alerts"] == result["deleted_incidents"] == 2
            for _ in range(2):
                await cleanup_monitoring_data(db)
            assert await db.scalar(select(func.count()).select_from(CollectorRun)) == 0
            assert await db.scalar(select(func.count()).select_from(Incident)) == 0
            remaining = (await db.scalars(select(Alert))).all()
            assert len(remaining) == 1 and remaining[0].status == "active"

    run(scenario())
