"""Daily metric rollup query operations."""

from datetime import date
from typing import Any

from sqlalchemy import desc, distinct, func, select
from sqlalchemy.sql import Select

from .base import MetricRepositoryBase
from ...models.device import Device
from ...models.latest_metric import LatestMetric
from ...models.metric_daily_rollup import MetricDailyRollup
from ...models.metric_cold_archive import MetricColdArchive
from ...models.metric_site_type_daily_summary import MetricSiteTypeDailySummary
from ...core.time import utcnow


class MetricRollupMixin(MetricRepositoryBase):
    """Daily-summary metric repository methods."""

    async def list_metric_names(self, device_id: int | None = None) -> list[str]:
        """Return metric names currently present in latest snapshots."""
        query = select(distinct(LatestMetric.metric_name)).order_by(LatestMetric.metric_name)
        if device_id is not None:
            query = query.where(LatestMetric.device_id == device_id)
        return list((await self.db.scalars(query)).all())

    def _daily_summary_query(
        self,
        *,
        device_id: int | None = None,
        site: str | None = None,
        device_type: str | None = None,
        rollup_from: date | None = None,
        rollup_to: date | None = None,
    ) -> Select[Any]:
        """Build the base query for daily metric rollup rows."""
        query = (
            select(
                MetricDailyRollup.id,
                MetricDailyRollup.device_id,
                Device.name.label("device_name"),
                Device.device_type.label("device_type"),
                Device.site.label("site"),
                MetricDailyRollup.rollup_date,
                MetricDailyRollup.total_samples,
                MetricDailyRollup.ping_samples,
                MetricDailyRollup.down_count,
                MetricDailyRollup.uptime_percentage,
                MetricDailyRollup.average_ping_ms,
                MetricDailyRollup.min_ping_ms,
                MetricDailyRollup.max_ping_ms,
                MetricDailyRollup.average_packet_loss_percent,
                MetricDailyRollup.average_jitter_ms,
                MetricDailyRollup.max_jitter_ms,
                MetricDailyRollup.updated_at,
            )
            .outerjoin(Device, Device.id == MetricDailyRollup.device_id)
        )
        if device_id is not None:
            query = query.where(MetricDailyRollup.device_id == device_id)
        if str(site or "").strip():
            query = query.where(Device.site == str(site).strip())
        if str(device_type or "").strip():
            query = query.where(Device.device_type == str(device_type).strip())
        if rollup_from is not None:
            query = query.where(MetricDailyRollup.rollup_date >= rollup_from)
        if rollup_to is not None:
            query = query.where(MetricDailyRollup.rollup_date <= rollup_to)
        return query

    async def list_daily_summary_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        device_id: int | None = None,
        site: str | None = None,
        device_type: str | None = None,
        rollup_from: date | None = None,
        rollup_to: date | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List daily summary rows paged for metric repository queries."""
        rows = (
            await self.db.execute(
                self._daily_summary_query(
                    device_id=device_id,
                    site=site,
                    device_type=device_type,
                    rollup_from=rollup_from,
                    rollup_to=rollup_to,
                )
                .order_by(desc(MetricDailyRollup.rollup_date), Device.name.asc(), MetricDailyRollup.device_id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        payload = [
            {
                "id": row.id,
                "device_id": row.device_id,
                "device_name": row.device_name or "Unknown Device",
                "device_type": row.device_type,
                "site": row.site,
                "rollup_date": row.rollup_date,
                "total_samples": row.total_samples,
                "ping_samples": row.ping_samples,
                "down_count": row.down_count,
                "uptime_percentage": row.uptime_percentage,
                "average_ping_ms": row.average_ping_ms,
                "min_ping_ms": row.min_ping_ms,
                "max_ping_ms": row.max_ping_ms,
                "average_packet_loss_percent": row.average_packet_loss_percent,
                "average_jitter_ms": row.average_jitter_ms,
                "max_jitter_ms": row.max_jitter_ms,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
        if offset == 0 and len(payload) < limit:
            return payload, len(payload)
        return payload, await self.count_daily_summary_rows(
            device_id=device_id,
            site=site,
            device_type=device_type,
            rollup_from=rollup_from,
            rollup_to=rollup_to,
        )

    async def count_daily_summary_rows(
        self,
        *,
        device_id: int | None = None,
        site: str | None = None,
        device_type: str | None = None,
        rollup_from: date | None = None,
        rollup_to: date | None = None,
    ) -> int:
        """Count daily summary rows for metric repository queries."""
        query = select(func.count()).select_from(MetricDailyRollup).outerjoin(Device, Device.id == MetricDailyRollup.device_id)
        if device_id is not None:
            query = query.where(MetricDailyRollup.device_id == device_id)
        if str(site or "").strip():
            query = query.where(Device.site == str(site).strip())
        if str(device_type or "").strip():
            query = query.where(Device.device_type == str(device_type).strip())
        if rollup_from is not None:
            query = query.where(MetricDailyRollup.rollup_date >= rollup_from)
        if rollup_to is not None:
            query = query.where(MetricDailyRollup.rollup_date <= rollup_to)
        return int(await self.db.scalar(query) or 0)

    async def list_long_term_trend_rows(
        self,
        *,
        rollup_from: date | None = None,
        rollup_to: date | None = None,
        site: str | None = None,
        device_type: str | None = None,
        limit: int = 365,
    ) -> list[dict[str, Any]]:
        """Return materialized long-term daily trends grouped by site and device type."""
        query = select(MetricSiteTypeDailySummary)
        if rollup_from is not None:
            query = query.where(MetricSiteTypeDailySummary.summary_date >= rollup_from)
        if rollup_to is not None:
            query = query.where(MetricSiteTypeDailySummary.summary_date <= rollup_to)
        normalized_site = str(site or "").strip()
        if normalized_site:
            query = query.where(MetricSiteTypeDailySummary.site == normalized_site)
        normalized_device_type = str(device_type or "").strip()
        if normalized_device_type:
            query = query.where(MetricSiteTypeDailySummary.device_type == normalized_device_type)
        query = query.order_by(MetricSiteTypeDailySummary.summary_date.desc(), MetricSiteTypeDailySummary.site.asc()).limit(limit)
        rows = list((await self.db.scalars(query)).all())
        return [
            {
                "summary_date": row.summary_date,
                "site": row.site,
                "device_type": row.device_type,
                "device_count": row.device_count,
                "total_samples": row.total_samples,
                "ping_samples": row.ping_samples,
                "down_count": row.down_count,
                "average_uptime_percentage": row.average_uptime_percentage,
                "average_ping_ms": row.average_ping_ms,
                "average_packet_loss_percent": row.average_packet_loss_percent,
                "average_jitter_ms": row.average_jitter_ms,
                "max_jitter_ms": row.max_jitter_ms,
            }
            for row in rows
        ]

    async def list_cold_archive_rows(
        self,
        *,
        archive_from: date | None = None,
        archive_to: date | None = None,
        metric_name: str | None = None,
        site: str | None = None,
        device_type: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return cold archive rows joined with device metadata."""
        query = (
            select(
                MetricColdArchive.id,
                MetricColdArchive.device_id,
                Device.name.label("device_name"),
                Device.device_type.label("device_type"),
                Device.site.label("site"),
                MetricColdArchive.archive_date,
                MetricColdArchive.archive_month,
                MetricColdArchive.metric_name,
                MetricColdArchive.status,
                MetricColdArchive.unit,
                MetricColdArchive.sample_count,
                MetricColdArchive.numeric_sample_count,
                MetricColdArchive.min_numeric_value,
                MetricColdArchive.max_numeric_value,
                MetricColdArchive.avg_numeric_value,
                MetricColdArchive.first_checked_at,
                MetricColdArchive.last_checked_at,
                MetricColdArchive.last_metric_value,
            )
            .outerjoin(Device, Device.id == MetricColdArchive.device_id)
        )
        conditions = _cold_archive_conditions(
            archive_from=archive_from,
            archive_to=archive_to,
            metric_name=metric_name,
            site=site,
            device_type=device_type,
        )
        if conditions:
            query = query.where(*conditions)
        rows = (
            await self.db.execute(
                query.order_by(desc(MetricColdArchive.archive_date), Device.name.asc(), MetricColdArchive.metric_name.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        total_query = select(func.count()).select_from(MetricColdArchive).outerjoin(Device, Device.id == MetricColdArchive.device_id)
        if conditions:
            total_query = total_query.where(*conditions)
        total = int(await self.db.scalar(total_query) or 0)
        return [
            {
                "id": row.id,
                "device_id": row.device_id,
                "device_name": row.device_name or "Unknown Device",
                "device_type": row.device_type,
                "site": row.site,
                "archive_date": row.archive_date,
                "archive_month": row.archive_month,
                "metric_name": row.metric_name,
                "status": row.status,
                "unit": row.unit,
                "sample_count": row.sample_count,
                "numeric_sample_count": row.numeric_sample_count,
                "min_numeric_value": row.min_numeric_value,
                "max_numeric_value": row.max_numeric_value,
                "avg_numeric_value": row.avg_numeric_value,
                "first_checked_at": row.first_checked_at,
                "last_checked_at": row.last_checked_at,
                "last_metric_value": row.last_metric_value,
            }
            for row in rows
        ], total

    async def refresh_site_type_daily_summaries(self, *, commit: bool = True) -> int:
        """Rebuild materialized daily summaries from metric daily rollups."""
        site_expr = func.coalesce(func.nullif(Device.site, ""), "Unassigned")
        device_type_expr = func.coalesce(func.nullif(Device.device_type, ""), "unknown")
        rows = (
            await self.db.execute(
                select(
                    MetricDailyRollup.rollup_date.label("summary_date"),
                    site_expr.label("site"),
                    device_type_expr.label("device_type"),
                    func.count(func.distinct(MetricDailyRollup.device_id)).label("device_count"),
                    func.sum(MetricDailyRollup.total_samples).label("total_samples"),
                    func.sum(MetricDailyRollup.ping_samples).label("ping_samples"),
                    func.sum(MetricDailyRollup.down_count).label("down_count"),
                    func.avg(MetricDailyRollup.uptime_percentage).label("average_uptime_percentage"),
                    func.avg(MetricDailyRollup.average_ping_ms).label("average_ping_ms"),
                    func.avg(MetricDailyRollup.average_packet_loss_percent).label("average_packet_loss_percent"),
                    func.avg(MetricDailyRollup.average_jitter_ms).label("average_jitter_ms"),
                    func.max(MetricDailyRollup.max_jitter_ms).label("max_jitter_ms"),
                )
                .outerjoin(Device, Device.id == MetricDailyRollup.device_id)
                .group_by(MetricDailyRollup.rollup_date, site_expr, device_type_expr)
            )
        ).all()
        existing = {
            (row.summary_date, row.site, row.device_type): row
            for row in (
                await self.db.scalars(select(MetricSiteTypeDailySummary))
            ).all()
        }
        now_value = utcnow()
        for row in rows:
            key = (row.summary_date, row.site, row.device_type)
            payload = {
                "summary_date": row.summary_date,
                "site": row.site,
                "device_type": row.device_type,
                "device_count": int(row.device_count or 0),
                "total_samples": int(row.total_samples or 0),
                "ping_samples": int(row.ping_samples or 0),
                "down_count": int(row.down_count or 0),
                "average_uptime_percentage": row.average_uptime_percentage,
                "average_ping_ms": row.average_ping_ms,
                "average_packet_loss_percent": row.average_packet_loss_percent,
                "average_jitter_ms": row.average_jitter_ms,
                "max_jitter_ms": row.max_jitter_ms,
            }
            existing_row = existing.get(key)
            if existing_row is None:
                self.db.add(MetricSiteTypeDailySummary(**payload))
                continue
            for field_name, value in payload.items():
                setattr(existing_row, field_name, value)
            existing_row.updated_at = now_value
        await self.db.flush()
        if commit:
            await self.db.commit()
        return len(rows)


def _cold_archive_conditions(
    *,
    archive_from: date | None,
    archive_to: date | None,
    metric_name: str | None,
    site: str | None,
    device_type: str | None,
):
    conditions = []
    if archive_from is not None:
        conditions.append(MetricColdArchive.archive_date >= archive_from)
    if archive_to is not None:
        conditions.append(MetricColdArchive.archive_date <= archive_to)
    if metric_name:
        conditions.append(MetricColdArchive.metric_name == metric_name)
    if site:
        conditions.append(Device.site == site)
    if device_type:
        conditions.append(Device.device_type == device_type)
    return conditions
