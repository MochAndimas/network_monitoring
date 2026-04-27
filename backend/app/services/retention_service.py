"""Define module logic for `backend/app/services/retention_service.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from math import inf

from shared.collection_utils import chunked
from shared.number_utils import safe_float
from sqlalchemy import and_, delete, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.alert import Alert
from ..models.incident import Incident
from ..models.latest_metric import LatestMetric
from ..models.metric import Metric
from ..models.metric_cold_archive import MetricColdArchive
from ..models.metric_daily_rollup import MetricDailyRollup
from ..core.time import utcnow


UP_STATUSES = {"up", "ok"}


async def cleanup_monitoring_data(db: AsyncSession, *, commit: bool = True) -> dict[str, int]:
    """Run full retention workflow for rollups, archives, and expiry cleanup.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Aggregate completed raw metrics into daily rollup records.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    cutoff = _today_start()
    processed = 0
    batch_size = max(int(settings.retention_rollup_batch_size), 1)
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
    """Delete raw metrics older than configured retention windows.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Archive expired raw metrics into cold-storage aggregate tables.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    cutoff = _raw_metric_cutoff()
    processed = 0
    batch_size = max(int(settings.retention_archive_batch_size), 1)
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
    """Delete resolved alerts older than configured retention windows.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    cutoff = utcnow() - timedelta(days=settings.alert_retention_days)
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
    """Delete resolved incidents older than configured retention windows.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    cutoff = utcnow() - timedelta(days=settings.incident_retention_days)
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
    """Perform raw metric cutoff.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    cutoff_date = (utcnow() - timedelta(days=settings.raw_metric_retention_days)).date()
    return datetime.combine(cutoff_date, time.min)


def _today_start() -> datetime:
    """Perform today start.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return datetime.combine(utcnow().date(), time.min)


async def _iter_rollup_payloads(db: AsyncSession, cutoff: datetime):
    """Perform iter rollup payloads.

    Args:
        db: Parameter input untuk routine ini.
        cutoff: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    query = (
        select(
            Metric.device_id,
            Metric.checked_at,
            Metric.metric_name,
            Metric.metric_value,
            Metric.status,
        )
        .where(Metric.checked_at < cutoff)
        .order_by(Metric.device_id.asc(), Metric.checked_at.asc(), Metric.id.asc())
    )
    result = await db.stream(query)
    current_key: tuple[int, object] | None = None
    current_accumulator: _RollupAccumulator | None = None
    async for device_id, checked_at, metric_name, metric_value, status in result:
        key = (int(device_id), checked_at.date())
        if current_key != key:
            if current_accumulator is not None and current_key is not None:
                yield current_key, current_accumulator.to_payload()
            current_key = key
            current_accumulator = _RollupAccumulator(device_id=key[0], rollup_date=key[1])
        assert current_accumulator is not None
        current_accumulator.add(metric_name, metric_value, status)

    if current_accumulator is not None and current_key is not None:
        yield current_key, current_accumulator.to_payload()


async def _iter_archive_payloads(db: AsyncSession, cutoff: datetime):
    """Perform iter archive payloads.

    Args:
        db: Parameter input untuk routine ini.
        cutoff: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    query = (
        select(
            Metric.device_id,
            Metric.checked_at,
            Metric.metric_name,
            Metric.metric_value,
            Metric.status,
            Metric.unit,
        )
        .where(Metric.checked_at < cutoff)
        .order_by(
            Metric.device_id.asc(),
            func.date(Metric.checked_at).asc(),
            Metric.metric_name.asc(),
            func.lower(func.coalesce(Metric.status, "unknown")).asc(),
            func.coalesce(Metric.unit, "").asc(),
            Metric.checked_at.asc(),
            Metric.id.asc(),
        )
    )
    result = await db.stream(query)
    current_key: tuple[int, object, str, str, str] | None = None
    current_accumulator: _ArchiveAccumulator | None = None
    async for device_id, checked_at, metric_name, metric_value, status, unit in result:
        archive_date = checked_at.date()
        normalized_status = str(status or "unknown").lower()
        normalized_unit = str(unit or "")
        key = (int(device_id), archive_date, str(metric_name), normalized_status, normalized_unit)
        if current_key != key:
            if current_accumulator is not None and current_key is not None:
                yield current_key, current_accumulator.to_payload()
            current_key = key
            current_accumulator = _ArchiveAccumulator(
                device_id=int(device_id),
                archive_date=archive_date,
                metric_name=str(metric_name),
                status=normalized_status,
                unit=normalized_unit,
            )
        assert current_accumulator is not None
        current_accumulator.add(metric_value=str(metric_value), checked_at=checked_at)

    if current_accumulator is not None and current_key is not None:
        yield current_key, current_accumulator.to_payload()


async def _upsert_rollup_payloads(db: AsyncSession, payloads: dict[tuple[int, object], dict]) -> None:
    """Upsert rollup payloads.

    Args:
        db: Parameter input untuk routine ini.
        payloads: Parameter input untuk routine ini.

    """
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
    await db.flush()


async def _upsert_archive_payloads(db: AsyncSession, payloads: dict[tuple[int, object, str, str, str], dict]) -> None:
    """Upsert archive payloads.

    Args:
        db: Parameter input untuk routine ini.
        payloads: Parameter input untuk routine ini.

    """
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
    await db.flush()


async def _load_existing_rollups(db: AsyncSession, keys) -> dict[tuple[int, object], MetricDailyRollup]:
    """Load existing rollups.

    Args:
        db: Parameter input untuk routine ini.
        keys: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Load existing archives.

    Args:
        db: Parameter input untuk routine ini.
        keys: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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


class _RollupAccumulator:
    """Perform RollupAccumulator.

    This class encapsulates related behavior and data for this domain area.
    """

    def __init__(self, *, device_id: int, rollup_date) -> None:
        """Perform init.

        Args:
            device_id: Parameter input untuk routine ini.
            rollup_date: Parameter input untuk routine ini.

        """
        self.device_id = device_id
        self.rollup_date = rollup_date
        self.total_samples = 0
        self.ping_samples = 0
        self.down_count = 0
        self.uptime_count = 0
        self.ping_sum = 0.0
        self.ping_value_count = 0
        self.min_ping_ms = inf
        self.max_ping_ms = float("-inf")
        self.packet_loss_sum = 0.0
        self.packet_loss_count = 0
        self.jitter_sum = 0.0
        self.jitter_count = 0
        self.max_jitter_ms = float("-inf")

    def add(self, metric_name: str, metric_value: str, status: str | None) -> None:
        """Consume one raw metric sample into rollup counters.

        Args:
            metric_name: Parameter input untuk routine ini.
            metric_value: Parameter input untuk routine ini.
            status: Parameter input untuk routine ini.

        """
        self.total_samples += 1
        normalized_status = str(status or "").lower()

        if metric_name == "ping":
            self.ping_samples += 1
            if normalized_status == "down":
                self.down_count += 1
            if normalized_status in UP_STATUSES:
                self.uptime_count += 1
            self._track_ping(metric_value)
            return

        if metric_name == "packet_loss":
            self._track_packet_loss(metric_value)
            return

        if metric_name == "jitter":
            self._track_jitter(metric_value)

    def to_payload(self) -> dict:
        """Build ORM-ready rollup payload from accumulated counters.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        return {
            "device_id": self.device_id,
            "rollup_date": self.rollup_date,
            "total_samples": self.total_samples,
            "ping_samples": self.ping_samples,
            "down_count": self.down_count,
            "uptime_percentage": (self.uptime_count / self.ping_samples) * 100 if self.ping_samples else None,
            "average_ping_ms": (self.ping_sum / self.ping_value_count) if self.ping_value_count else None,
            "min_ping_ms": self.min_ping_ms if self.ping_value_count else None,
            "max_ping_ms": self.max_ping_ms if self.ping_value_count else None,
            "average_packet_loss_percent": (self.packet_loss_sum / self.packet_loss_count) if self.packet_loss_count else None,
            "average_jitter_ms": (self.jitter_sum / self.jitter_count) if self.jitter_count else None,
            "max_jitter_ms": self.max_jitter_ms if self.jitter_count else None,
        }

    def _track_ping(self, metric_value: str) -> None:
        """Perform track ping.

        Args:
            metric_value: Parameter input untuk routine ini.

        """
        value = safe_float(metric_value)
        if value is None:
            return
        self.ping_sum += value
        self.ping_value_count += 1
        self.min_ping_ms = min(self.min_ping_ms, value)
        self.max_ping_ms = max(self.max_ping_ms, value)

    def _track_packet_loss(self, metric_value: str) -> None:
        """Perform track packet loss.

        Args:
            metric_value: Parameter input untuk routine ini.

        """
        value = safe_float(metric_value)
        if value is None:
            return
        self.packet_loss_sum += value
        self.packet_loss_count += 1

    def _track_jitter(self, metric_value: str) -> None:
        """Perform track jitter.

        Args:
            metric_value: Parameter input untuk routine ini.

        """
        value = safe_float(metric_value)
        if value is None:
            return
        self.jitter_sum += value
        self.jitter_count += 1
        self.max_jitter_ms = max(self.max_jitter_ms, value)


class _ArchiveAccumulator:
    """Perform ArchiveAccumulator.

    This class encapsulates related behavior and data for this domain area.
    """

    def __init__(
        self,
        *,
        device_id: int,
        archive_date,
        metric_name: str,
        status: str,
        unit: str,
    ) -> None:
        """Perform init.

        Args:
            device_id: Parameter input untuk routine ini.
            archive_date: Parameter input untuk routine ini.
            metric_name: Parameter input untuk routine ini.
            status: Parameter input untuk routine ini.
            unit: Parameter input untuk routine ini.

        """
        self.device_id = device_id
        self.archive_date = archive_date
        self.metric_name = metric_name
        self.status = status
        self.unit = unit
        self.sample_count = 0
        self.numeric_sample_count = 0
        self.numeric_sum = 0.0
        self.min_numeric_value = inf
        self.max_numeric_value = float("-inf")
        self.first_checked_at: datetime | None = None
        self.last_checked_at: datetime | None = None
        self.last_metric_value = ""

    def add(self, *, metric_value: str, checked_at: datetime) -> None:
        """Consume one raw metric sample into archive aggregate counters.

        Args:
            metric_value: Parameter input untuk routine ini.
            checked_at: Parameter input untuk routine ini.

        """
        self.sample_count += 1
        if self.first_checked_at is None:
            self.first_checked_at = checked_at
        self.last_checked_at = checked_at
        self.last_metric_value = metric_value
        value = safe_float(metric_value)
        if value is None:
            return
        self.numeric_sample_count += 1
        self.numeric_sum += value
        self.min_numeric_value = min(self.min_numeric_value, value)
        self.max_numeric_value = max(self.max_numeric_value, value)

    def to_payload(self) -> dict:
        """Build ORM-ready cold-archive payload from accumulated counters.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        archive_month = self.archive_date.replace(day=1)
        return {
            "device_id": self.device_id,
            "archive_date": self.archive_date,
            "archive_month": archive_month,
            "metric_name": self.metric_name,
            "status": self.status,
            "unit": self.unit,
            "sample_count": self.sample_count,
            "numeric_sample_count": self.numeric_sample_count,
            "min_numeric_value": self.min_numeric_value if self.numeric_sample_count else None,
            "max_numeric_value": self.max_numeric_value if self.numeric_sample_count else None,
            "avg_numeric_value": (self.numeric_sum / self.numeric_sample_count) if self.numeric_sample_count else None,
            "first_checked_at": self.first_checked_at,
            "last_checked_at": self.last_checked_at,
            "last_metric_value": self.last_metric_value,
        }
