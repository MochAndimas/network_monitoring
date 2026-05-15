"""Service-layer workflows for retention service."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from shared.collection_utils import chunked
from sqlalchemy import and_, case, delete, exists, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.alert import Alert
from ..models.incident import Incident
from ..models.latest_metric import LatestMetric
from ..models.metric import Metric
from ..models.metric_cold_archive import MetricColdArchive
from ..models.metric_daily_rollup import MetricDailyRollup
from ..models.retention_bucket_progress import RetentionBucketProgress
from ..core.time import utcnow


UP_STATUSES = {"up", "ok"}


def case_when(condition, value, else_value=None):
    """Return a compact SQL CASE expression for aggregate filters."""
    return case((condition, value), else_=else_value)


async def cleanup_monitoring_data(db: AsyncSession, *, commit: bool = True) -> dict[str, int]:
    """Roll up, archive, and prune monitoring records according to retention settings."""
    rolled_up_days = await rollup_completed_raw_metrics(db, commit=False)
    archived_metric_groups = await archive_expired_raw_metrics(db, commit=False)
    deleted_metrics = await delete_expired_raw_metrics(db, commit=False)
    deleted_alerts = await delete_expired_alerts(db, commit=False)
    deleted_incidents = await delete_expired_incidents(db, commit=False)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {
        "rolled_up_days": rolled_up_days,
        "archived_metric_groups": archived_metric_groups,
        "deleted_metrics": deleted_metrics,
        "deleted_alerts": deleted_alerts,
        "deleted_incidents": deleted_incidents,
    }


async def rollup_completed_raw_metrics(db: AsyncSession, *, commit: bool = True) -> int:
    """Aggregate completed raw metric days into daily rollup rows."""
    cutoff = _today_start()
    processed = 0
    batch_size = max(int(settings.retention.rollup_batch_size), 1)
    pending_payloads: dict[tuple[int, object], dict] = {}

    async for key, payload in _iter_rollup_payloads(db, cutoff):
        pending_payloads[key] = payload
        if len(pending_payloads) < batch_size:
            continue
        await _upsert_rollup_payloads(db, pending_payloads)
        processed += len(pending_payloads)
        pending_payloads = {}

    if pending_payloads:
        await _upsert_rollup_payloads(db, pending_payloads)
        processed += len(pending_payloads)

    if commit:
        await db.commit()
    else:
        await db.flush()
    return processed


async def delete_expired_raw_metrics(db: AsyncSession, *, commit: bool = True) -> int:
    """Delete expired raw metrics while preserving latest snapshot references."""
    cutoff = _raw_metric_cutoff()
    retained_latest_metric_ids = select(LatestMetric.metric_id).where(LatestMetric.metric_id.is_not(None))
    result = await db.execute(
        delete(Metric).where(
            Metric.checked_at < cutoff,
            Metric.id.not_in(retained_latest_metric_ids),
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return int(getattr(result, "rowcount", 0) or 0)


async def archive_expired_raw_metrics(db: AsyncSession, *, commit: bool = True) -> int:
    """Aggregate expired raw metrics into cold archive rows."""
    cutoff = _raw_metric_cutoff()
    processed = 0
    batch_size = max(int(settings.retention.archive_batch_size), 1)
    pending_payloads: dict[tuple[int, object, str, str, str], dict] = {}

    async for key, payload in _iter_archive_payloads(db, cutoff):
        pending_payloads[key] = payload
        if len(pending_payloads) < batch_size:
            continue
        await _upsert_archive_payloads(db, pending_payloads)
        processed += len(pending_payloads)
        pending_payloads = {}

    if pending_payloads:
        await _upsert_archive_payloads(db, pending_payloads)
        processed += len(pending_payloads)

    if commit:
        await db.commit()
    else:
        await db.flush()
    return processed


async def delete_expired_alerts(db: AsyncSession, *, commit: bool = True) -> int:
    """Delete resolved alert rows outside the retention window."""
    cutoff = utcnow() - timedelta(days=settings.retention.alert_days)
    result = await db.execute(
        delete(Alert).where(
            Alert.status != "active",
            or_(
                Alert.resolved_at < cutoff,
                and_(Alert.resolved_at.is_(None), Alert.created_at < cutoff),
            ),
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return int(getattr(result, "rowcount", 0) or 0)


async def delete_expired_incidents(db: AsyncSession, *, commit: bool = True) -> int:
    """Delete resolved incident rows outside the retention window."""
    cutoff = utcnow() - timedelta(days=settings.retention.incident_days)
    result = await db.execute(
        delete(Incident).where(
            Incident.status != "active",
            or_(
                Incident.ended_at < cutoff,
                and_(Incident.ended_at.is_(None), Incident.started_at < cutoff),
            ),
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return int(getattr(result, "rowcount", 0) or 0)


def _raw_metric_cutoff() -> datetime:
    """Return the oldest raw metric timestamp that should remain online."""
    cutoff_date = (utcnow() - timedelta(days=settings.retention.raw_metric_days)).date()
    return datetime.combine(cutoff_date, time.min)


def _today_start() -> datetime:
    """Return midnight UTC for the current day."""
    return datetime.combine(utcnow().date(), time.min)


def _coerce_date(value) -> date:
    """Normalize database date buckets across SQLite and MySQL drivers."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


async def _iter_rollup_payloads(db: AsyncSession, cutoff: datetime):
    """Stream SQL-aggregated raw metrics grouped into daily rollup payloads."""
    bucket_date = func.date(Metric.checked_at)
    query = (
        select(
            Metric.device_id,
            bucket_date.label("rollup_date"),
            func.count(Metric.id).label("total_samples"),
            func.sum(case_when(Metric.metric_name == "ping", 1, 0)).label("ping_samples"),
            func.sum(
                case_when(
                    and_(Metric.metric_name == "ping", func.lower(func.coalesce(Metric.status, "")) == "down"),
                    1,
                    0,
                )
            ).label("down_count"),
            func.sum(
                case_when(
                    and_(
                        Metric.metric_name == "ping",
                        func.lower(func.coalesce(Metric.status, "")).in_(UP_STATUSES),
                    ),
                    1,
                    0,
                )
            ).label("uptime_count"),
            func.avg(case_when(Metric.metric_name == "ping", Metric.metric_value_numeric)).label("average_ping_ms"),
            func.min(case_when(Metric.metric_name == "ping", Metric.metric_value_numeric)).label("min_ping_ms"),
            func.max(case_when(Metric.metric_name == "ping", Metric.metric_value_numeric)).label("max_ping_ms"),
            func.avg(case_when(Metric.metric_name == "packet_loss", Metric.metric_value_numeric)).label(
                "average_packet_loss_percent"
            ),
            func.avg(case_when(Metric.metric_name == "jitter", Metric.metric_value_numeric)).label("average_jitter_ms"),
            func.max(case_when(Metric.metric_name == "jitter", Metric.metric_value_numeric)).label("max_jitter_ms"),
        )
        .where(Metric.checked_at < cutoff)
        .where(
            ~exists(
                select(RetentionBucketProgress.id).where(
                    RetentionBucketProgress.bucket_kind == "rollup",
                    RetentionBucketProgress.device_id == Metric.device_id,
                    RetentionBucketProgress.bucket_date == bucket_date,
                    RetentionBucketProgress.metric_name == "",
                    RetentionBucketProgress.status == "",
                    RetentionBucketProgress.unit == "",
                )
            )
        )
        .group_by(Metric.device_id, bucket_date)
        .order_by(Metric.device_id.asc(), bucket_date.asc())
    )
    async for row in await db.stream(query):
        rollup_date = _coerce_date(row.rollup_date)
        ping_samples = int(row.ping_samples or 0)
        uptime_count = int(row.uptime_count or 0)
        payload = {
            "device_id": int(row.device_id),
            "rollup_date": rollup_date,
            "total_samples": int(row.total_samples or 0),
            "ping_samples": ping_samples,
            "down_count": int(row.down_count or 0),
            "uptime_percentage": (uptime_count / ping_samples) * 100 if ping_samples else None,
            "average_ping_ms": row.average_ping_ms,
            "min_ping_ms": row.min_ping_ms,
            "max_ping_ms": row.max_ping_ms,
            "average_packet_loss_percent": row.average_packet_loss_percent,
            "average_jitter_ms": row.average_jitter_ms,
            "max_jitter_ms": row.max_jitter_ms,
        }
        yield (int(row.device_id), rollup_date), payload


async def _iter_archive_payloads(db: AsyncSession, cutoff: datetime):
    """Stream SQL-aggregated raw metrics grouped into cold archive payloads."""
    archive_date = func.date(Metric.checked_at)
    normalized_status = func.lower(func.coalesce(Metric.status, "unknown"))
    normalized_unit = func.coalesce(Metric.unit, "")
    ranked_metrics = (
        select(
            Metric.device_id.label("device_id"),
            archive_date.label("archive_date"),
            Metric.metric_name.label("metric_name"),
            normalized_status.label("status"),
            normalized_unit.label("unit"),
            Metric.metric_value.label("metric_value"),
            Metric.metric_value_numeric.label("metric_value_numeric"),
            Metric.checked_at.label("checked_at"),
            func.row_number()
            .over(
                partition_by=(
                    Metric.device_id,
                    archive_date,
                    Metric.metric_name,
                    normalized_status,
                    normalized_unit,
                ),
                order_by=(Metric.checked_at.desc(), Metric.id.desc()),
            )
            .label("value_rank"),
        )
        .where(Metric.checked_at < cutoff)
        .where(
            ~exists(
                select(RetentionBucketProgress.id).where(
                    RetentionBucketProgress.bucket_kind == "archive",
                    RetentionBucketProgress.device_id == Metric.device_id,
                    RetentionBucketProgress.bucket_date == archive_date,
                    RetentionBucketProgress.metric_name == Metric.metric_name,
                    RetentionBucketProgress.status == normalized_status,
                    RetentionBucketProgress.unit == normalized_unit,
                )
            )
        )
        .subquery()
    )
    query = (
        select(
            ranked_metrics.c.device_id,
            ranked_metrics.c.archive_date,
            ranked_metrics.c.metric_name,
            ranked_metrics.c.status,
            ranked_metrics.c.unit,
            func.count().label("sample_count"),
            func.count(ranked_metrics.c.metric_value_numeric).label("numeric_sample_count"),
            func.min(ranked_metrics.c.metric_value_numeric).label("min_numeric_value"),
            func.max(ranked_metrics.c.metric_value_numeric).label("max_numeric_value"),
            func.avg(ranked_metrics.c.metric_value_numeric).label("avg_numeric_value"),
            func.min(ranked_metrics.c.checked_at).label("first_checked_at"),
            func.max(ranked_metrics.c.checked_at).label("last_checked_at"),
            func.max(case_when(ranked_metrics.c.value_rank == 1, ranked_metrics.c.metric_value)).label(
                "last_metric_value"
            ),
        )
        .group_by(
            ranked_metrics.c.device_id,
            ranked_metrics.c.archive_date,
            ranked_metrics.c.metric_name,
            ranked_metrics.c.status,
            ranked_metrics.c.unit,
        )
        .order_by(
            ranked_metrics.c.device_id.asc(),
            ranked_metrics.c.archive_date.asc(),
            ranked_metrics.c.metric_name.asc(),
            ranked_metrics.c.status.asc(),
            ranked_metrics.c.unit.asc(),
        )
    )
    async for row in await db.stream(query):
        archive_date_value = _coerce_date(row.archive_date)
        key = (
            int(row.device_id),
            archive_date_value,
            str(row.metric_name),
            str(row.status or "unknown"),
            str(row.unit or ""),
        )
        payload = {
            "device_id": key[0],
            "archive_date": archive_date_value,
            "archive_month": archive_date_value.replace(day=1),
            "metric_name": key[2],
            "status": key[3],
            "unit": key[4],
            "sample_count": int(row.sample_count or 0),
            "numeric_sample_count": int(row.numeric_sample_count or 0),
            "min_numeric_value": row.min_numeric_value,
            "max_numeric_value": row.max_numeric_value,
            "avg_numeric_value": row.avg_numeric_value,
            "first_checked_at": row.first_checked_at,
            "last_checked_at": row.last_checked_at,
            "last_metric_value": str(row.last_metric_value or ""),
        }
        yield key, payload


async def _upsert_rollup_payloads(db: AsyncSession, payloads: dict[tuple[int, object], dict]) -> None:
    """Insert or update daily rollup payloads by device and day."""
    existing_rollups = await _load_existing_rollups(db, payloads.keys())
    now = utcnow()
    for key, payload in payloads.items():
        payload["updated_at"] = now
        existing = existing_rollups.get(key)
        if existing is None:
            db.add(MetricDailyRollup(**payload))
            continue
        for field_name, value in payload.items():
            setattr(existing, field_name, value)
    await _mark_rollup_buckets_processed(db, payloads.keys(), processed_at=now)
    await db.flush()


async def _upsert_archive_payloads(db: AsyncSession, payloads: dict[tuple[int, object, str, str, str], dict]) -> None:
    """Insert or update cold archive payloads by device, day, metric, status, and unit."""
    existing_archives = await _load_existing_archives(db, payloads.keys())
    now = utcnow()
    for key, payload in payloads.items():
        payload["updated_at"] = now
        existing = existing_archives.get(key)
        if existing is None:
            db.add(MetricColdArchive(**payload))
            continue
        for field_name, value in payload.items():
            setattr(existing, field_name, value)
    await _mark_archive_buckets_processed(db, payloads.keys(), processed_at=now)
    await db.flush()


async def _mark_rollup_buckets_processed(db: AsyncSession, keys, *, processed_at: datetime) -> None:
    """Persist processed markers for rollup buckets that have been aggregated."""
    key_list = list(keys)
    if not key_list:
        return
    marker_keys = [(int(device_id), bucket_date, "", "", "") for device_id, bucket_date in key_list]
    existing_markers = await _load_existing_retention_markers(db, "rollup", marker_keys)
    for device_id, bucket_date, metric_name, status, unit in marker_keys:
        marker = existing_markers.get((device_id, bucket_date, metric_name, status, unit))
        if marker is None:
            db.add(
                RetentionBucketProgress(
                    bucket_kind="rollup",
                    device_id=device_id,
                    bucket_date=bucket_date,
                    metric_name=metric_name,
                    status=status,
                    unit=unit,
                    processed_at=processed_at,
                )
            )
        else:
            marker.processed_at = processed_at


async def _mark_archive_buckets_processed(db: AsyncSession, keys, *, processed_at: datetime) -> None:
    """Persist processed markers for archive buckets that have been aggregated."""
    key_list = [(int(device_id), bucket_date, metric_name, status, unit) for device_id, bucket_date, metric_name, status, unit in keys]
    if not key_list:
        return
    existing_markers = await _load_existing_retention_markers(db, "archive", key_list)
    for device_id, bucket_date, metric_name, status, unit in key_list:
        marker = existing_markers.get((device_id, bucket_date, metric_name, status, unit))
        if marker is None:
            db.add(
                RetentionBucketProgress(
                    bucket_kind="archive",
                    device_id=device_id,
                    bucket_date=bucket_date,
                    metric_name=metric_name,
                    status=status,
                    unit=unit,
                    processed_at=processed_at,
                )
            )
        else:
            marker.processed_at = processed_at


async def _load_existing_rollups(db: AsyncSession, keys) -> dict[tuple[int, object], MetricDailyRollup]:
    """Load existing daily rollup rows for the requested keys."""
    key_list = list(keys)
    if not key_list:
        return {}

    existing: dict[tuple[int, object], MetricDailyRollup] = {}
    for chunk in chunked(key_list, 500):
        query = select(MetricDailyRollup).where(
            tuple_(MetricDailyRollup.device_id, MetricDailyRollup.rollup_date).in_(chunk)
        )
        for rollup in (await db.scalars(query)).all():
            existing[(rollup.device_id, rollup.rollup_date)] = rollup
    return existing


async def _load_existing_archives(db: AsyncSession, keys) -> dict[tuple[int, object, str, str, str], MetricColdArchive]:
    """Load existing cold archive rows for the requested keys."""
    key_list = list(keys)
    if not key_list:
        return {}

    existing: dict[tuple[int, object, str, str, str], MetricColdArchive] = {}
    for chunk in chunked(key_list, 250):
        query = select(MetricColdArchive).where(
            tuple_(
                MetricColdArchive.device_id,
                MetricColdArchive.archive_date,
                MetricColdArchive.metric_name,
                MetricColdArchive.status,
                MetricColdArchive.unit,
            ).in_(chunk)
        )
        for archive in (await db.scalars(query)).all():
            existing[
                (
                    archive.device_id,
                    archive.archive_date,
                    archive.metric_name,
                    archive.status,
                    archive.unit,
                )
            ] = archive
    return existing


async def _load_existing_retention_markers(
    db: AsyncSession,
    bucket_kind: str,
    keys,
) -> dict[tuple[int, object, str, str, str], RetentionBucketProgress]:
    """Load processed retention markers for the requested bucket keys."""
    key_list = list(keys)
    if not key_list:
        return {}

    existing: dict[tuple[int, object, str, str, str], RetentionBucketProgress] = {}
    for chunk in chunked(key_list, 250):
        query = select(RetentionBucketProgress).where(
            RetentionBucketProgress.bucket_kind == bucket_kind,
            tuple_(
                RetentionBucketProgress.device_id,
                RetentionBucketProgress.bucket_date,
                RetentionBucketProgress.metric_name,
                RetentionBucketProgress.status,
                RetentionBucketProgress.unit,
            ).in_(chunk),
        )
        for marker in (await db.scalars(query)).all():
            existing[
                (
                    marker.device_id,
                    marker.bucket_date,
                    marker.metric_name,
                    marker.status,
                    marker.unit,
                )
            ] = marker
    return existing

