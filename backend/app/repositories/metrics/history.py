"""Metric history query operations."""

from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, desc, func, or_, select

from .base import MetricRepositoryBase
from ...models.device import Device
from ...models.metric import Metric


class MetricHistoryMixin(MetricRepositoryBase):
    """History-query metric repository methods."""

    async def list_recent_metrics(
        self,
        limit: int = 100,
        device_id: int | None = None,
        metric_name: str | None = None,
        status: str | None = None,
    ) -> list[Metric]:
        """Return recent metric ORM rows ordered newest first."""
        query: Select[tuple[Metric]] = select(Metric)
        if device_id is not None:
            query = query.where(Metric.device_id == device_id)
        if metric_name:
            query = query.where(Metric.metric_name == metric_name)
        if status:
            query = query.where(Metric.status == status)
        query = query.order_by(desc(Metric.checked_at), desc(Metric.id)).limit(limit)
        return list((await self.db.scalars(query)).all())

    async def list_recent_metrics_by_device(
        self,
        *,
        device_ids: list[int],
        metric_name: str,
        per_device_limit: int = 2,
    ) -> dict[int, list[Metric]]:
        """Return a bounded recent-history list for each requested device."""
        if not device_ids or per_device_limit < 1:
            return {}

        ranked_metrics = (
            select(
                Metric.id.label("metric_id"),
                Metric.device_id.label("device_id"),
                func.row_number()
                .over(
                    partition_by=Metric.device_id,
                    order_by=(desc(Metric.checked_at), desc(Metric.id)),
                )
                .label("row_number"),
            )
            .where(
                Metric.metric_name == metric_name,
                Metric.device_id.in_(device_ids),
            )
            .subquery()
        )
        query = (
            select(Metric)
            .join(ranked_metrics, Metric.id == ranked_metrics.c.metric_id)
            .where(ranked_metrics.c.row_number <= per_device_limit)
            .order_by(Metric.device_id.asc(), desc(Metric.checked_at), desc(Metric.id))
        )
        metrics = list((await self.db.scalars(query)).all())
        payload: dict[int, list[Metric]] = {}
        for metric in metrics:
            payload.setdefault(int(metric.device_id), []).append(metric)
        return payload

    async def list_recent_metric_rows(
        self,
        limit: int = 100,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from: datetime | None = None,
        checked_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent metric rows in API dictionary form."""
        query = self._recent_metric_rows_query(
            device_id=device_id,
            metric_name=metric_name,
            metric_names=metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        rows = (await self.db.execute(query.order_by(desc(Metric.checked_at), desc(Metric.id)).limit(limit))).all()
        return [self._metric_row_payload(row) for row in rows]

    async def list_recent_metric_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        per_metric_limit: int | None = None,
        status: str | None = None,
        checked_from: datetime | None = None,
        checked_to: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return paginated metric history rows and the matching total count."""
        normalized_metric_names = self._normalize_metric_names(metric_names)
        if normalized_metric_names and per_metric_limit is not None and offset == 0:
            return await self._list_recent_metric_rows_per_metric_limit(
                device_id=device_id,
                metric_name=metric_name,
                metric_names=normalized_metric_names,
                per_metric_limit=per_metric_limit,
                status=status,
                checked_from=checked_from,
                checked_to=checked_to,
            )

        rows = (
            await self.db.execute(
                self._recent_metric_rows_query(
                    device_id=device_id,
                    metric_name=metric_name,
                    metric_names=normalized_metric_names,
                    status=status,
                    checked_from=checked_from,
                    checked_to=checked_to,
                )
                .order_by(desc(Metric.checked_at), desc(Metric.id))
                .offset(offset)
                .limit(limit)
            )
        ).all()
        payload = [self._metric_row_payload(row) for row in rows]
        if offset == 0 and len(payload) < limit:
            return payload, len(payload)
        if not payload and offset > 0:
            total = await self.count_recent_metric_rows(
                device_id=device_id,
                metric_name=metric_name,
                metric_names=normalized_metric_names,
                status=status,
                checked_from=checked_from,
                checked_to=checked_to,
            )
            return payload, total
        total = await self.count_recent_metric_rows(
            device_id=device_id,
            metric_name=metric_name,
            metric_names=normalized_metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        return payload, total

    async def list_recent_metric_rows_after_cursor(
        self,
        *,
        limit: int = 100,
        cursor_checked_at: datetime | None,
        cursor_id: int,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from: datetime | None = None,
        checked_to: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return the next metric-history page using keyset pagination."""
        normalized_metric_names = self._normalize_metric_names(metric_names)
        query = self._recent_metric_rows_query(
            device_id=device_id,
            metric_name=metric_name,
            metric_names=normalized_metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        if cursor_checked_at is not None:
            query = query.where(
                or_(
                    Metric.checked_at < cursor_checked_at,
                    and_(Metric.checked_at == cursor_checked_at, Metric.id < cursor_id),
                )
            )
        rows = (
            await self.db.execute(
                query.order_by(desc(Metric.checked_at), desc(Metric.id)).limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        return [self._metric_row_payload(row) for row in rows[:limit]], has_more

    async def _list_recent_metric_rows_per_metric_limit(
        self,
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str],
        per_metric_limit: int,
        status: str | None = None,
        checked_from: datetime | None = None,
        checked_to: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return the newest rows per metric name for multi-metric trend views."""
        conditions = self._recent_metric_filter_conditions(
            device_id=device_id,
            metric_name=metric_name,
            metric_names=metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        ranked_metrics = (
            select(
                Metric.id.label("metric_id"),
                Metric.metric_name.label("metric_name"),
                func.row_number()
                .over(
                    partition_by=Metric.metric_name,
                    order_by=(desc(Metric.checked_at), desc(Metric.id)),
                )
                .label("row_number"),
            )
            .where(*conditions)
            .subquery()
        )
        rows = (
            await self.db.execute(
                select(
                    Metric.id,
                    Metric.device_id,
                    Device.name.label("device_name"),
                    Metric.metric_name,
                    Metric.metric_value,
                    Metric.metric_value_numeric,
                    Metric.status,
                    Metric.unit,
                    Metric.checked_at,
                )
                .join(ranked_metrics, Metric.id == ranked_metrics.c.metric_id)
                .outerjoin(Device, Device.id == Metric.device_id)
                .where(ranked_metrics.c.row_number <= per_metric_limit)
                .order_by(desc(Metric.checked_at), desc(Metric.id))
            )
        ).all()
        payload = [self._metric_row_payload(row) for row in rows]
        return payload, len(payload)

    async def count_recent_metric_rows(
        self,
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from: datetime | None = None,
        checked_to: datetime | None = None,
    ) -> int:
        """Count raw metric history rows matching the active filters."""
        query = select(func.count()).select_from(Metric)
        conditions = self._recent_metric_filter_conditions(
            device_id=device_id,
            metric_name=metric_name,
            metric_names=metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        if conditions:
            query = query.where(*conditions)
        return int(await self.db.scalar(query) or 0)
