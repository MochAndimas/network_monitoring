"""Service-layer workflows for retention service."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from shared.collection_utils import chunked
from sqlalchemy import and_, case, delete, func, or_, select, tuple_
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
from ..models.device import Device
from ..repositories.metric_repository import MetricRepository


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
    compacted_latest_metrics = await compact_latest_snapshot(db, commit=False)
    refreshed_site_type_summaries = await MetricRepository(db).refresh_site_type_daily_summaries(commit=False)
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
        "compacted_latest_metrics": compacted_latest_metrics,
        "refreshed_site_type_summaries": refreshed_site_type_summaries,
    }


async def compact_latest_snapshot(db: AsyncSession, *, commit: bool = True) -> int:
    """Remove stale latest-snapshot rows that no longer help dashboard reads."""
    inactive_device_ids = select(Device.id).where(Device.is_active.is_(False))
    inactive_result = await db.execute(delete(LatestMetric).where(LatestMetric.device_id.in_(inactive_device_ids)))
    if commit:
        await db.commit()
    else:
        await db.flush()
    return int(getattr(inactive_result, "rowcount", 0) or 0)


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
    marker_match = and_(
        RetentionBucketProgress.bucket_kind == "rollup",
        RetentionBucketProgress.device_id == Metric.device_id,
        RetentionBucketProgress.bucket_date == bucket_date,
        RetentionBucketProgress.metric_name == "",
        RetentionBucketProgress.status == "",
        RetentionBucketProgress.unit == "",
    )
    query = (
        select(
            Metric.device_id,
            bucket_date.label("rollup_date"),
            RetentionBucketProgress.source_metric_count.label("previous_source_metric_count"),
            RetentionBucketProgress.source_max_metric_id.label("previous_source_max_metric_id"),
            RetentionBucketProgress.source_latest_checked_at.label("previous_source_latest_checked_at"),
            func.count(Metric.id).label("total_samples"),
            func.sum(case_when(Metric.metric_name == "ping", 1, 0)).label("ping_samples"),
            func.count(case_when(Metric.metric_name == "ping", Metric.metric_value_numeric)).label(
                "ping_numeric_samples"
            ),
            func.sum(case_when(Metric.metric_name == "packet_loss", 1, 0)).label("packet_loss_samples"),
            func.count(case_when(Metric.metric_name == "packet_loss", Metric.metric_value_numeric)).label(
                "packet_loss_numeric_samples"
            ),
            func.sum(case_when(Metric.metric_name == "jitter", 1, 0)).label("jitter_samples"),
            func.count(case_when(Metric.metric_name == "jitter", Metric.metric_value_numeric)).label(
                "jitter_numeric_samples"
            ),
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
            func.max(Metric.id).label("source_max_metric_id"),
            func.max(Metric.checked_at).label("source_latest_checked_at"),
        )
        .select_from(Metric)
        .outerjoin(RetentionBucketProgress, marker_match)
        .where(Metric.checked_at < cutoff)
        .where(
            or_(
                RetentionBucketProgress.id.is_(None),
                RetentionBucketProgress.source_max_metric_id.is_(None),
                Metric.id > RetentionBucketProgress.source_max_metric_id,
            )
        )
        .group_by(Metric.device_id, bucket_date)
        .group_by(
            RetentionBucketProgress.source_metric_count,
            RetentionBucketProgress.source_max_metric_id,
            RetentionBucketProgress.source_latest_checked_at,
        )
        .order_by(Metric.device_id.asc(), bucket_date.asc())
    )
    async for row in await db.stream(query):
        rollup_date = _coerce_date(row.rollup_date)
        ping_samples = int(row.ping_samples or 0)
        ping_numeric_samples = int(row.ping_numeric_samples or 0)
        packet_loss_samples = int(row.packet_loss_samples or 0)
        packet_loss_numeric_samples = int(row.packet_loss_numeric_samples or 0)
        jitter_samples = int(row.jitter_samples or 0)
        jitter_numeric_samples = int(row.jitter_numeric_samples or 0)
        uptime_count = int(row.uptime_count or 0)
        payload = {
            "device_id": int(row.device_id),
            "rollup_date": rollup_date,
            "total_samples": int(row.total_samples or 0),
            "ping_samples": ping_samples,
            "ping_numeric_samples": ping_numeric_samples,
            "packet_loss_samples": packet_loss_samples,
            "packet_loss_numeric_samples": packet_loss_numeric_samples,
            "jitter_samples": jitter_samples,
            "jitter_numeric_samples": jitter_numeric_samples,
            "down_count": int(row.down_count or 0),
            "uptime_percentage": (uptime_count / ping_samples) * 100 if ping_samples else None,
            "average_ping_ms": row.average_ping_ms,
            "min_ping_ms": row.min_ping_ms,
            "max_ping_ms": row.max_ping_ms,
            "average_packet_loss_percent": row.average_packet_loss_percent,
            "average_jitter_ms": row.average_jitter_ms,
            "max_jitter_ms": row.max_jitter_ms,
            "_uptime_count": uptime_count,
            "_source_metric_count": int(row.total_samples or 0),
            "_source_max_metric_id": int(row.source_max_metric_id) if row.source_max_metric_id is not None else None,
            "_source_latest_checked_at": row.source_latest_checked_at,
            "_previous_source_metric_count": int(row.previous_source_metric_count or 0),
            "_previous_source_max_metric_id": (
                int(row.previous_source_max_metric_id) if row.previous_source_max_metric_id is not None else None
            ),
            "_previous_source_latest_checked_at": row.previous_source_latest_checked_at,
        }
        yield (int(row.device_id), rollup_date), payload


async def _iter_archive_payloads(db: AsyncSession, cutoff: datetime):
    """Stream SQL-aggregated raw metrics grouped into cold archive payloads."""
    archive_date = func.date(Metric.checked_at)
    normalized_status = func.lower(func.coalesce(Metric.status, "unknown"))
    normalized_unit = func.coalesce(Metric.unit, "")
    marker_match = and_(
        RetentionBucketProgress.bucket_kind == "archive",
        RetentionBucketProgress.device_id == Metric.device_id,
        RetentionBucketProgress.bucket_date == archive_date,
        RetentionBucketProgress.metric_name == Metric.metric_name,
        RetentionBucketProgress.status == normalized_status,
        RetentionBucketProgress.unit == normalized_unit,
    )
    ranked_metrics = (
        select(
            Metric.device_id.label("device_id"),
            archive_date.label("archive_date"),
            Metric.metric_name.label("metric_name"),
            normalized_status.label("status"),
            normalized_unit.label("unit"),
            RetentionBucketProgress.source_metric_count.label("previous_source_metric_count"),
            RetentionBucketProgress.source_max_metric_id.label("previous_source_max_metric_id"),
            RetentionBucketProgress.source_latest_checked_at.label("previous_source_latest_checked_at"),
            Metric.metric_value.label("metric_value"),
            Metric.metric_value_numeric.label("metric_value_numeric"),
            Metric.checked_at.label("checked_at"),
            Metric.id.label("metric_id"),
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
        .select_from(Metric)
        .outerjoin(RetentionBucketProgress, marker_match)
        .where(Metric.checked_at < cutoff)
        .where(
            or_(
                RetentionBucketProgress.id.is_(None),
                RetentionBucketProgress.source_max_metric_id.is_(None),
                Metric.id > RetentionBucketProgress.source_max_metric_id,
            )
        )
        .subquery()
    )
    archive_aggregates = (
        select(
            ranked_metrics.c.device_id,
            ranked_metrics.c.archive_date,
            ranked_metrics.c.metric_name,
            ranked_metrics.c.status,
            ranked_metrics.c.unit,
            ranked_metrics.c.previous_source_metric_count,
            ranked_metrics.c.previous_source_max_metric_id,
            ranked_metrics.c.previous_source_latest_checked_at,
            func.count().label("sample_count"),
            func.count(ranked_metrics.c.metric_value_numeric).label("numeric_sample_count"),
            func.min(ranked_metrics.c.metric_value_numeric).label("min_numeric_value"),
            func.max(ranked_metrics.c.metric_value_numeric).label("max_numeric_value"),
            func.avg(ranked_metrics.c.metric_value_numeric).label("avg_numeric_value"),
            func.min(ranked_metrics.c.checked_at).label("first_checked_at"),
            func.max(ranked_metrics.c.checked_at).label("last_checked_at"),
            func.max(ranked_metrics.c.metric_id).label("source_max_metric_id"),
            func.max(ranked_metrics.c.checked_at).label("source_latest_checked_at"),
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
            ranked_metrics.c.previous_source_metric_count,
            ranked_metrics.c.previous_source_max_metric_id,
            ranked_metrics.c.previous_source_latest_checked_at,
        )
        .subquery()
    )
    query = (
        select(archive_aggregates)
        .order_by(
            archive_aggregates.c.device_id.asc(),
            archive_aggregates.c.archive_date.asc(),
            archive_aggregates.c.metric_name.asc(),
            archive_aggregates.c.status.asc(),
            archive_aggregates.c.unit.asc(),
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
            "_source_metric_count": int(row.sample_count or 0),
            "_source_max_metric_id": int(row.source_max_metric_id) if row.source_max_metric_id is not None else None,
            "_source_latest_checked_at": row.source_latest_checked_at,
            "_previous_source_metric_count": int(row.previous_source_metric_count or 0),
            "_previous_source_max_metric_id": (
                int(row.previous_source_max_metric_id) if row.previous_source_max_metric_id is not None else None
            ),
            "_previous_source_latest_checked_at": row.previous_source_latest_checked_at,
        }
        yield key, payload


async def _upsert_rollup_payloads(db: AsyncSession, payloads: dict[tuple[int, object], dict]) -> None:
    """Insert or update daily rollup payloads by device and day."""
    existing_rollups = await _load_existing_rollups(db, payloads.keys())
    now = utcnow()
    for key, payload in payloads.items():
        payload["updated_at"] = now
        existing = existing_rollups.get(key)
        _prepare_marker_source(payload, existing is not None)
        rollup_payload = _model_payload(payload)
        if existing is None:
            db.add(MetricDailyRollup(**rollup_payload))
            continue
        if _should_merge_incrementally(payload):
            _merge_rollup_payload(existing, payload)
            continue
        for field_name, value in rollup_payload.items():
            setattr(existing, field_name, value)
    await _mark_rollup_buckets_processed(db, payloads, processed_at=now)
    await db.flush()


async def _upsert_archive_payloads(db: AsyncSession, payloads: dict[tuple[int, object, str, str, str], dict]) -> None:
    """Insert or update cold archive payloads by device, day, metric, status, and unit."""
    existing_archives = await _load_existing_archives(db, payloads.keys())
    now = utcnow()
    for key, payload in payloads.items():
        payload["updated_at"] = now
        existing = existing_archives.get(key)
        _prepare_marker_source(payload, existing is not None)
        archive_payload = _model_payload(payload)
        if existing is None:
            db.add(MetricColdArchive(**archive_payload))
            continue
        if _should_merge_incrementally(payload):
            _merge_archive_payload(existing, payload)
            continue
        for field_name, value in archive_payload.items():
            setattr(existing, field_name, value)
    await _mark_archive_buckets_processed(db, payloads, processed_at=now)
    await db.flush()


def _model_payload(payload: dict) -> dict:
    """Return fields intended for ORM model construction/update."""
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def _should_merge_incrementally(payload: dict) -> bool:
    """Return whether a processed bucket should merge late rows instead of replacing the aggregate."""
    previous_max_id = payload.get("_previous_source_max_metric_id")
    source_max_id = payload.get("_source_max_metric_id")
    return previous_max_id is not None and source_max_id != previous_max_id


def _prepare_marker_source(payload: dict, existing_aggregate: bool) -> None:
    """Store the represented source fingerprint that should be written to the marker."""
    source_count = int(payload.get("_source_metric_count") or 0)
    source_max_id = payload.get("_source_max_metric_id")
    source_latest_checked_at = payload.get("_source_latest_checked_at")
    if existing_aggregate and _should_merge_incrementally(payload):
        previous_count = int(payload.get("_previous_source_metric_count") or 0)
        previous_max_id = payload.get("_previous_source_max_metric_id")
        previous_latest_checked_at = payload.get("_previous_source_latest_checked_at")
        payload["_marker_source_metric_count"] = previous_count + source_count
        payload["_marker_source_max_metric_id"] = _max_optional(previous_max_id, source_max_id)
        payload["_marker_source_latest_checked_at"] = _max_optional(previous_latest_checked_at, source_latest_checked_at)
        return
    payload["_marker_source_metric_count"] = source_count
    payload["_marker_source_max_metric_id"] = source_max_id
    payload["_marker_source_latest_checked_at"] = source_latest_checked_at


def _merge_rollup_payload(existing: MetricDailyRollup, payload: dict) -> None:
    """Merge late-arriving raw metrics into an existing daily rollup aggregate."""
    previous_ping_samples = int(existing.ping_samples or 0)
    incoming_ping_samples = int(payload["ping_samples"] or 0)
    previous_ping_numeric_samples = int(existing.ping_numeric_samples or 0)
    incoming_ping_numeric_samples = int(payload["ping_numeric_samples"] or 0)
    previous_packet_loss_samples = int(existing.packet_loss_samples or 0)
    incoming_packet_loss_samples = int(payload["packet_loss_samples"] or 0)
    previous_packet_loss_numeric_samples = int(existing.packet_loss_numeric_samples or 0)
    incoming_packet_loss_numeric_samples = int(payload["packet_loss_numeric_samples"] or 0)
    previous_jitter_samples = int(existing.jitter_samples or 0)
    incoming_jitter_samples = int(payload["jitter_samples"] or 0)
    previous_jitter_numeric_samples = int(existing.jitter_numeric_samples or 0)
    incoming_jitter_numeric_samples = int(payload["jitter_numeric_samples"] or 0)

    existing.total_samples = int(existing.total_samples or 0) + int(payload["total_samples"] or 0)
    existing.ping_samples = previous_ping_samples + incoming_ping_samples
    existing.ping_numeric_samples = previous_ping_numeric_samples + incoming_ping_numeric_samples
    existing.packet_loss_samples = previous_packet_loss_samples + incoming_packet_loss_samples
    existing.packet_loss_numeric_samples = previous_packet_loss_numeric_samples + incoming_packet_loss_numeric_samples
    existing.jitter_samples = previous_jitter_samples + incoming_jitter_samples
    existing.jitter_numeric_samples = previous_jitter_numeric_samples + incoming_jitter_numeric_samples
    existing.down_count = int(existing.down_count or 0) + int(payload["down_count"] or 0)

    previous_uptime_count = _uptime_count_from_percentage(existing.uptime_percentage, previous_ping_samples)
    incoming_uptime_count = int(payload.get("_uptime_count") or 0)
    existing.uptime_percentage = (
        ((previous_uptime_count + incoming_uptime_count) / existing.ping_samples) * 100
        if existing.ping_samples
        else None
    )
    existing.average_ping_ms = _weighted_average(
        existing.average_ping_ms,
        previous_ping_numeric_samples,
        payload["average_ping_ms"],
        incoming_ping_numeric_samples,
    )
    existing.min_ping_ms = _min_optional(existing.min_ping_ms, payload["min_ping_ms"])
    existing.max_ping_ms = _max_optional(existing.max_ping_ms, payload["max_ping_ms"])
    existing.average_packet_loss_percent = _weighted_average(
        existing.average_packet_loss_percent,
        previous_packet_loss_numeric_samples,
        payload["average_packet_loss_percent"],
        incoming_packet_loss_numeric_samples,
    )
    existing.average_jitter_ms = _weighted_average(
        existing.average_jitter_ms,
        previous_jitter_numeric_samples,
        payload["average_jitter_ms"],
        incoming_jitter_numeric_samples,
    )
    existing.max_jitter_ms = _max_optional(existing.max_jitter_ms, payload["max_jitter_ms"])
    existing.updated_at = payload["updated_at"]


def _merge_archive_payload(existing: MetricColdArchive, payload: dict) -> None:
    """Merge late-arriving raw metrics into an existing cold archive aggregate."""
    previous_numeric_count = int(existing.numeric_sample_count or 0)
    incoming_numeric_count = int(payload["numeric_sample_count"] or 0)
    existing.sample_count = int(existing.sample_count or 0) + int(payload["sample_count"] or 0)
    existing.numeric_sample_count = previous_numeric_count + incoming_numeric_count
    existing.min_numeric_value = _min_optional(existing.min_numeric_value, payload["min_numeric_value"])
    existing.max_numeric_value = _max_optional(existing.max_numeric_value, payload["max_numeric_value"])
    existing.avg_numeric_value = _weighted_average(
        existing.avg_numeric_value,
        previous_numeric_count,
        payload["avg_numeric_value"],
        incoming_numeric_count,
    )
    existing.first_checked_at = _min_optional(existing.first_checked_at, payload["first_checked_at"])
    if payload["last_checked_at"] >= existing.last_checked_at:
        existing.last_checked_at = payload["last_checked_at"]
        existing.last_metric_value = str(payload["last_metric_value"] or "")
    existing.updated_at = payload["updated_at"]


def _uptime_count_from_percentage(uptime_percentage: float | None, ping_samples: int) -> int:
    """Reconstruct the stored uptime count from percentage and ping sample count."""
    if uptime_percentage is None or ping_samples <= 0:
        return 0
    return int(round((float(uptime_percentage) / 100) * ping_samples))


def _weighted_average(existing_value, existing_count: int, incoming_value, incoming_count: int):
    """Combine two averages using their sample counts."""
    if incoming_value is None or incoming_count <= 0:
        return existing_value
    if existing_value is None or existing_count <= 0:
        return incoming_value
    return ((float(existing_value) * existing_count) + (float(incoming_value) * incoming_count)) / (
        existing_count + incoming_count
    )


def _min_optional(left, right):
    """Return the smaller non-null value."""
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _max_optional(left, right):
    """Return the larger non-null value."""
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


async def _mark_rollup_buckets_processed(db: AsyncSession, payloads: dict, *, processed_at: datetime) -> None:
    """Persist processed markers for rollup buckets that have been aggregated."""
    key_list = list(payloads.keys())
    if not key_list:
        return
    marker_keys = [(int(device_id), bucket_date, "", "", "") for device_id, bucket_date in key_list]
    existing_markers = await _load_existing_retention_markers(db, "rollup", marker_keys)
    for device_id, bucket_date, metric_name, status, unit in marker_keys:
        marker = existing_markers.get((device_id, bucket_date, metric_name, status, unit))
        if marker is None:
            marker = RetentionBucketProgress(
                bucket_kind="rollup",
                device_id=device_id,
                bucket_date=bucket_date,
                metric_name=metric_name,
                status=status,
                unit=unit,
                processed_at=processed_at,
            )
            db.add(marker)
        else:
            marker.processed_at = processed_at
        payload = payloads[(device_id, bucket_date)]
        marker.source_metric_count = int(payload["_marker_source_metric_count"] or 0)
        marker.source_max_metric_id = payload["_marker_source_max_metric_id"]
        marker.source_latest_checked_at = payload["_marker_source_latest_checked_at"]


async def _mark_archive_buckets_processed(db: AsyncSession, payloads: dict, *, processed_at: datetime) -> None:
    """Persist processed markers for archive buckets that have been aggregated."""
    key_list = [
        (int(device_id), bucket_date, metric_name, status, unit)
        for device_id, bucket_date, metric_name, status, unit in payloads.keys()
    ]
    if not key_list:
        return
    existing_markers = await _load_existing_retention_markers(db, "archive", key_list)
    for device_id, bucket_date, metric_name, status, unit in key_list:
        marker = existing_markers.get((device_id, bucket_date, metric_name, status, unit))
        if marker is None:
            marker = RetentionBucketProgress(
                bucket_kind="archive",
                device_id=device_id,
                bucket_date=bucket_date,
                metric_name=metric_name,
                status=status,
                unit=unit,
                processed_at=processed_at,
            )
            db.add(marker)
        else:
            marker.processed_at = processed_at
        payload = payloads[(device_id, bucket_date, metric_name, status, unit)]
        marker.source_metric_count = int(payload["_marker_source_metric_count"] or 0)
        marker.source_max_metric_id = payload["_marker_source_max_metric_id"]
        marker.source_latest_checked_at = payload["_marker_source_latest_checked_at"]


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

