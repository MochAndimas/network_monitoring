"""Bounded retention selection with source checkpoints and writer coordination."""

from datetime import datetime
from typing import Literal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ..models.device import Device
from ..models.latest_metric import LatestMetric
from ..models.metric import Metric
from ..models.metric_cold_archive import MetricColdArchive
from ..models.metric_daily_rollup import MetricDailyRollup
from ..models.retention_bucket_progress import RetentionBucketProgress

BucketKind = Literal["rollup", "archive"]


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
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def source_batch(self, kind: BucketKind, cutoff: datetime, limit: int) -> list[int]:
        # Acquire the same device lock as append-only metric writers BEFORE reading
        # source IDs. MySQL locking reads see commits that preceded lock acquisition,
        # including lower auto-increment IDs from a delayed writer transaction.
        pending = and_(Metric.checked_at < cutoff, or_(~represented(kind), ~aggregate_exists(kind)))
        device_id = await self.db.scalar(
            select(Device.id)
            .where(select(Metric.id).where(Metric.device_id == Device.id, pending).exists())
            .order_by(Device.id)
            .limit(1)
            .with_for_update()
        )
        if device_id is None:
            return []
        corrupt = await self.db.scalar(
            select(Metric.id)
            .where(
                Metric.device_id == device_id,
                Metric.checked_at < cutoff,
                represented(kind),
                ~aggregate_exists(kind),
            )
            .limit(1)
            .with_for_update()
        )
        if corrupt is not None:
            raise ValueError("Retention checkpoint has no aggregate; restore it before pruning")
        return list(
            (
                await self.db.scalars(
                    select(Metric.id)
                    .where(Metric.device_id == device_id, pending)
                    .order_by(Metric.id)
                    .limit(limit)
                    .with_for_update()
                )
            ).all()
        )

    async def delete_raw_batch(self, cutoff: datetime, limit: int) -> int:
        safe = and_(
            Metric.checked_at < cutoff,
            represented("rollup"),
            aggregate_exists("rollup"),
            represented("archive"),
            aggregate_exists("archive"),
            ~select(LatestMetric.id).where(LatestMetric.metric_id == Metric.id).exists(),
        )
        device_id = await self.db.scalar(
            select(Device.id)
            .where(select(Metric.id).where(Metric.device_id == Device.id, safe).exists())
            .order_by(Device.id)
            .limit(1)
            .with_for_update()
        )
        if device_id is None:
            return 0
        ids = list(
            (
                await self.db.scalars(
                    select(Metric.id)
                    .where(Metric.device_id == device_id, safe)
                    .order_by(Metric.id)
                    .limit(limit)
                    .with_for_update()
                )
            ).all()
        )
        if not ids:
            return 0
        result = await self.db.execute(
            delete(Metric).where(Metric.id.in_(ids), safe).execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)
