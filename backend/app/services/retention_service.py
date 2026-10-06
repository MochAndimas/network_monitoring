"""Resumable retention: each operational batch commits its own checkpoint."""

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.time import utcnow
from ..models.alert import Alert
from ..models.collector_run import CollectorRun
from ..models.device import Device
from ..models.incident import Incident
from ..models.latest_metric import LatestMetric
from ..models.retention_bucket_progress import RetentionBucketProgress
from ..models.metric_daily_rollup import MetricDailyRollup
from ..models.metric_site_type_daily_summary import MetricSiteTypeDailySummary
from ..repositories.metric_repository import MetricRepository
from ..repositories.retention_repository import BucketKind, RetentionRepository
from .retention_batches import delete_rows_in_batches, finish_retention_batch
from .retention_aggregates import (
    _iter_archive_payloads,
    _iter_rollup_payloads,
    _upsert_archive_payloads,
    _upsert_rollup_payloads,
)


async def cleanup_monitoring_data(db: AsyncSession, *, commit: bool = True) -> dict[str, int]:
    """Process bounded batches; commit=False leaves all ownership to the caller.

    Operational callers must use a clean session and hold the cleanup advisory
    lock for the entire run. Earlier batches survive a failure; retry resumes from
    aggregate/checkpoint pairs. Never mix unrelated pending writes into this session.
    """
    if commit and (db.new or db.dirty or db.deleted):
        raise ValueError("Operational retention requires a session without pending unrelated writes")
    try:
        return {
            "rolled_up_days": await rollup_completed_raw_metrics(db, commit=commit),
            "archived_metric_groups": await archive_expired_raw_metrics(db, commit=commit),
            "deleted_metrics": await delete_expired_raw_metrics(db, commit=commit),
            "deleted_collector_runs": await delete_expired_collector_runs(db, commit=commit),
            "deleted_alerts": await delete_expired_alerts(db, commit=commit),
            "deleted_incidents": await delete_expired_incidents(db, commit=commit),
            "compacted_latest_metrics": await compact_latest_snapshot(db, commit=commit),
            "refreshed_site_type_summaries": await refresh_pending_summaries(db, commit=commit),
        }
    except BaseException:
        if commit:
            await db.rollback()
        raise


async def _aggregate_batches(db: AsyncSession, kind: BucketKind, cutoff: datetime, *, commit: bool) -> int:
    repository = RetentionRepository(db)
    group_limit = settings.retention.rollup_batch_size if kind == "rollup" else settings.retention.archive_batch_size
    limit = min(settings.retention.source_batch_size, max(group_limit, 1))
    processed: set[Any] = set()
    for _ in range(settings.retention.max_batches_per_phase):
        ids = await repository.source_batch(kind, cutoff, limit)
        if not ids:
            await finish_retention_batch(db, commit)
            break
        if kind == "rollup":
            rollup_payloads = {key: payload async for key, payload in _iter_rollup_payloads(db, cutoff, ids)}
            if not rollup_payloads:
                raise RuntimeError("Retention source batch disappeared before aggregation")
            await _upsert_rollup_payloads(db, rollup_payloads)
            processed.update(rollup_payloads)
        else:
            archive_payloads = {key: payload async for key, payload in _iter_archive_payloads(db, cutoff, ids)}
            if not archive_payloads:
                raise RuntimeError("Retention source batch disappeared before aggregation")
            await _upsert_archive_payloads(db, archive_payloads)
            processed.update(archive_payloads)
        await finish_retention_batch(db, commit)
    return len(processed)


async def rollup_completed_raw_metrics(db: AsyncSession, *, commit: bool = True) -> int:
    return await _aggregate_batches(db, "rollup", _today_start(), commit=commit)


async def archive_expired_raw_metrics(db: AsyncSession, *, commit: bool = True) -> int:
    return await _aggregate_batches(db, "archive", _raw_metric_cutoff(), commit=commit)


async def delete_expired_raw_metrics(db: AsyncSession, *, commit: bool = True) -> int:
    total = 0
    repository = RetentionRepository(db)
    cutoff = _raw_metric_cutoff()
    for _ in range(settings.retention.max_batches_per_phase):
        count = await repository.delete_raw_batch(cutoff, settings.retention.delete_batch_size)
        await finish_retention_batch(db, commit)
        total += count
        if not count:
            break
    return total


async def delete_expired_collector_runs(db: AsyncSession, *, commit: bool = True) -> int:
    return await delete_rows_in_batches(db, CollectorRun, CollectorRun.checked_at < _raw_metric_cutoff(), commit=commit)


async def compact_latest_snapshot(db: AsyncSession, *, commit: bool = True) -> int:
    inactive_ids = select(Device.id).where(Device.is_active.is_(False))
    return await delete_rows_in_batches(db, LatestMetric, LatestMetric.device_id.in_(inactive_ids), commit=commit)


async def delete_expired_alerts(db: AsyncSession, *, commit: bool = True) -> int:
    cutoff = utcnow() - timedelta(days=settings.retention.alert_days)
    return await delete_rows_in_batches(
        db,
        Alert,
        and_(
            Alert.status != "active",
            or_(Alert.resolved_at < cutoff, and_(Alert.resolved_at.is_(None), Alert.created_at < cutoff)),
        ),
        commit=commit,
    )


async def delete_expired_incidents(db: AsyncSession, *, commit: bool = True) -> int:
    cutoff = utcnow() - timedelta(days=settings.retention.incident_days)
    return await delete_rows_in_batches(
        db,
        Incident,
        and_(
            Incident.status != "active",
            or_(Incident.ended_at < cutoff, and_(Incident.ended_at.is_(None), Incident.started_at < cutoff)),
        ),
        commit=commit,
    )


async def refresh_pending_summaries(db: AsyncSession, *, commit: bool = True) -> int:
    """Page summary groups and rotate completed days to reconcile metadata edits."""
    # Bootstrap historical dates after upgrade, without a migration or global rebuild.
    missing_dates = list(
        (
            await db.scalars(
                select(MetricDailyRollup.rollup_date)
                .where(
                    ~select(RetentionBucketProgress.id)
                    .where(
                        RetentionBucketProgress.bucket_kind == "summary",
                        RetentionBucketProgress.bucket_date == MetricDailyRollup.rollup_date,
                    )
                    .exists()
                )
                .distinct()
                .order_by(MetricDailyRollup.rollup_date)
                .limit(min(max(settings.retention.rollup_batch_size, 1), settings.retention.source_batch_size))
            )
        ).all()
    )
    for day in missing_dates:
        db.add(
            RetentionBucketProgress(
                bucket_kind="summary",
                device_id=0,
                bucket_date=day,
                metric_name="",
                status="",
                unit="",
                source_metric_count=0,
                processed_at=utcnow(),
            )
        )
    await finish_retention_batch(db, commit)
    total = 0
    completed: set[date] = set()
    page_size = min(max(settings.retention.rollup_batch_size, 1), settings.retention.source_batch_size)
    for _ in range(settings.retention.max_batches_per_phase):
        marker = await db.scalar(
            select(RetentionBucketProgress)
            .where(
                RetentionBucketProgress.bucket_kind == "summary",
                RetentionBucketProgress.bucket_date.not_in(completed),
            )
            .order_by(
                case((RetentionBucketProgress.source_max_metric_id.is_(None), 0), else_=1),
                RetentionBucketProgress.processed_at,
                RetentionBucketProgress.bucket_date,
            )
            .limit(1)
            .with_for_update()
        )
        if marker is None:
            await finish_retention_batch(db, commit)
            break
        count = await MetricRepository(db).refresh_site_type_daily_summaries(
            commit=False, summary_dates=[marker.bucket_date], limit=page_size, offset=marker.source_metric_count
        )
        total += count
        if count < page_size:
            marker.source_max_metric_id = 0
            marker.source_metric_count = 0
            marker.processed_at = utcnow()
            completed.add(marker.bucket_date)
        else:
            marker.source_max_metric_id = None
            marker.source_metric_count += count
        await finish_retention_batch(db, commit)
    # Metadata moves can leave obsolete site/type groups. Delete only bounded IDs.
    valid_group = (
        select(MetricDailyRollup.id)
        .outerjoin(Device, Device.id == MetricDailyRollup.device_id)
        .where(
            MetricDailyRollup.rollup_date == MetricSiteTypeDailySummary.summary_date,
            func.coalesce(func.nullif(Device.site, ""), "Unassigned") == MetricSiteTypeDailySummary.site,
            func.coalesce(func.nullif(Device.device_type, ""), "unknown") == MetricSiteTypeDailySummary.device_type,
        )
        .exists()
    )
    await delete_rows_in_batches(db, MetricSiteTypeDailySummary, ~valid_group, commit=commit)
    return total


def _raw_metric_cutoff() -> datetime:
    return datetime.combine((utcnow() - timedelta(days=settings.retention.raw_metric_days)).date(), time.min)


def _today_start() -> datetime:
    return datetime.combine(utcnow().date(), time.min)
