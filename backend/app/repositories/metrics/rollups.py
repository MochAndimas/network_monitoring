"""Daily metric rollup query operations."""

from sqlalchemy import desc, distinct, func, select

from .base import MetricRepositoryBase
from ...models.device import Device
from ...models.latest_metric import LatestMetric
from ...models.metric_daily_rollup import MetricDailyRollup


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
        rollup_from=None,
        rollup_to=None,
    ):
        """Build the base query for daily metric rollup rows."""
        query = (
            select(
                MetricDailyRollup.id,
                MetricDailyRollup.device_id,
                Device.name.label("device_name"),
                Device.device_type.label("device_type"),
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
        rollup_from=None,
        rollup_to=None,
    ) -> tuple[list[dict], int]:
        """List daily summary rows paged for metric repository queries."""
        rows = (
            await self.db.execute(
                self._daily_summary_query(
                    device_id=device_id,
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
            rollup_from=rollup_from,
            rollup_to=rollup_to,
        )

    async def count_daily_summary_rows(
        self,
        *,
        device_id: int | None = None,
        rollup_from=None,
        rollup_to=None,
    ) -> int:
        """Count daily summary rows for metric repository queries."""
        query = select(func.count()).select_from(MetricDailyRollup)
        if device_id is not None:
            query = query.where(MetricDailyRollup.device_id == device_id)
        if rollup_from is not None:
            query = query.where(MetricDailyRollup.rollup_date >= rollup_from)
        if rollup_to is not None:
            query = query.where(MetricDailyRollup.rollup_date <= rollup_to)
        return int(await self.db.scalar(query) or 0)
