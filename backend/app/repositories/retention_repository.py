"""Bounded retention selection with source checkpoints and writer coordination."""

from datetime import datetime
import logging
from typing import Literal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from ..core.phase_timing import timed_phase
from ..models.device import Device
from ..models.latest_metric import LatestMetric
from ..models.metric import Metric
from ..models.metric_cold_archive import MetricColdArchive
from ..models.metric_daily_rollup import MetricDailyRollup
from ..models.retention_bucket_progress import RetentionBucketProgress

BucketKind = Literal["rollup", "archive"]
logger = logging.getLogger("network_monitoring.retention")


def marker_conditions(kind: BucketKind) -> list[ColumnElement[bool]]:
    return [
        RetentionBucketProgress.bucket_kind == kind,
        RetentionBucketProgress.device_id == Metric.device_id,
        RetentionBucketProgress.bucket_date == func.date(Metric.checked_at),
        RetentionBucketProgress.metric_name == (Metric.metric_name if kind == "archive" else ""),
        RetentionBucketProgress.status
        == (func.lower(func.coalesce(Metric.status, "unknown")) if kind == "archive" else ""),
        RetentionBucketProgress.unit == (func.coalesce(Metric.unit, "") if kind == "archive" else ""),
    ]


def represented(kind: BucketKind) -> ColumnElement[bool]:
    return (
        select(RetentionBucketProgress.id)
        .where(*marker_conditions(kind), RetentionBucketProgress.source_max_metric_id >= Metric.id)
        .exists()
    )


def aggregate_exists(kind: BucketKind) -> ColumnElement[bool]:
    if kind == "rollup":
        return (
            select(MetricDailyRollup.id)
            .where(
                MetricDailyRollup.device_id == Metric.device_id,
                MetricDailyRollup.rollup_date == func.date(Metric.checked_at),
            )
            .exists()
        )
    return (
        select(MetricColdArchive.id)
        .where(
            MetricColdArchive.device_id == Metric.device_id,
            MetricColdArchive.archive_date == func.date(Metric.checked_at),
            MetricColdArchive.metric_name == Metric.metric_name,
            MetricColdArchive.status == func.lower(func.coalesce(Metric.status, "unknown")),
            MetricColdArchive.unit == func.coalesce(Metric.unit, ""),
        )
        .exists()
    )


class RetentionRepository:
    def __init__(self, db: AsyncSession, *, commit: bool = False) -> None:
        self.db = db
        self.commit = commit
        self._deferred_device_ids: set[int] = set()

    async def _lock_candidate_device(self, condition: ColumnElement[bool], phase: str) -> int | None:
        candidate = (
            select(Device.id)
            .where(select(Metric.id).where(Metric.device_id == Device.id, condition).exists())
            .order_by(Device.id)
            .limit(1)
        )
        if not self.commit:
            return await self.db.scalar(candidate.with_for_update())

        while True:
            with timed_phase(logger, "retention_candidate_lookup", phase):
                device_id = await self.db.scalar(candidate.where(Device.id.not_in(self._deferred_device_ids)))
            if device_id is None:
                return None

            # Establish the source snapshot only after acquiring the device lock.
            await self.db.commit()
            with timed_phase(logger, "retention_device_lock", phase):
                locked_id = await self.db.scalar(
                    select(Device.id).where(Device.id == device_id).with_for_update(skip_locked=True)
                )
            if locked_id is not None:
                return locked_id

            # Try other devices now. The next run can pick this one up from its checkpoint.
            await self.db.rollback()
            self._deferred_device_ids.add(device_id)
            logger.warning("retention_device_deferred phase=%s device_id=%s", phase, device_id)

    async def source_batch(self, kind: BucketKind, cutoff: datetime, limit: int) -> list[int]:
        # The device lock serializes source discovery with metric writers.
        pending = and_(Metric.checked_at < cutoff, or_(~represented(kind), ~aggregate_exists(kind)))
        device_id = await self._lock_candidate_device(pending, kind)
        if device_id is None:
            return []
        corrupt_query = (
            select(Metric.id)
            .where(
                Metric.device_id == device_id,
                Metric.checked_at < cutoff,
                represented(kind),
                ~aggregate_exists(kind),
            )
            .limit(1)
        )
        with timed_phase(logger, "retention_checkpoint_validation", "cleanup"):
            corrupt = await self.db.scalar(self._source_read(corrupt_query))
        if corrupt is not None:
            raise ValueError("Retention checkpoint has no aggregate; restore it before pruning")
        return await self._source_ids(device_id, pending, limit)

    def _source_read(self, query: Select[tuple[int]]) -> Select[tuple[int]]:
        # Operational batches establish a fresh snapshot after the device lock.
        # Caller-owned transactions may already have a snapshot and need a current read.
        return query if self.commit else query.with_for_update()

    async def _source_ids(self, device_id: int, condition: ColumnElement[bool], limit: int) -> list[int]:
        query = select(Metric.id).where(Metric.device_id == device_id, condition).order_by(Metric.id).limit(limit)
        with timed_phase(logger, "retention_source_lookup", "cleanup"):
            return list((await self.db.scalars(self._source_read(query))).all())

    async def delete_raw_batch(self, cutoff: datetime, limit: int) -> int:
        safe = and_(
            Metric.checked_at < cutoff,
            represented("rollup"),
            aggregate_exists("rollup"),
            represented("archive"),
            aggregate_exists("archive"),
            ~select(LatestMetric.id).where(LatestMetric.metric_id == Metric.id).exists(),
        )
        device_id = await self._lock_candidate_device(safe, "raw_metrics")
        if device_id is None:
            return 0
        ids = await self._source_ids(device_id, safe, limit)
        if not ids:
            return 0
        result = await self.db.execute(
            delete(Metric).where(Metric.id.in_(ids), safe).execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)
