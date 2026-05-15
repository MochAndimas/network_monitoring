"""Metric write and latest-snapshot update operations."""

from collections.abc import Iterable

from shared.collection_utils import chunked
from shared.number_utils import safe_float
from sqlalchemy import select, tuple_

from .base import MetricRepositoryBase
from ...models.latest_metric import LatestMetric
from ...models.metric import Metric
from .helpers import _is_metric_newer, _next_uptime_streak_started_at


class MetricWriteMixin(MetricRepositoryBase):
    """Write-side metric repository methods."""

    async def create_metrics(self, payloads: Iterable[dict], *, commit: bool = True) -> list[Metric]:
        """Insert a batch of raw metrics and update the latest-metric snapshot table."""
        metrics = [
                Metric(
                    **payload,
                    metric_value_numeric=payload.get("metric_value_numeric", safe_float(payload.get("metric_value"))),
                )
            for payload in payloads
        ]
        if not metrics:
            return []

        self.db.add_all(metrics)
        await self.db.flush()
        await self._upsert_latest_metrics(metrics)
        if commit:
            await self.db.commit()
        return metrics

    async def _upsert_latest_metrics(self, metrics: list[Metric]) -> None:
        """Update latest metric rows for the newest sample in each device/metric group."""
        grouped_metrics: dict[tuple[int, str], list[Metric]] = {}
        for metric in metrics:
            key = (int(metric.device_id), str(metric.metric_name))
            grouped_metrics.setdefault(key, []).append(metric)
        if not grouped_metrics:
            return

        latest_by_key = {
            key: max(
                metric_list,
                key=lambda metric: (metric.checked_at, int(metric.id)),
            )
            for key, metric_list in grouped_metrics.items()
        }
        keys = list(grouped_metrics.keys())
        existing_rows: dict[tuple[int, str], LatestMetric] = {}
        for chunk in chunked(keys, 250):
            query = select(LatestMetric).where(tuple_(LatestMetric.device_id, LatestMetric.metric_name).in_(chunk))
            for row in (await self.db.scalars(query)).all():
                existing_rows[(int(row.device_id), str(row.metric_name))] = row

        for key, metric in latest_by_key.items():
            existing = existing_rows.get(key)
            if existing is not None and not _is_metric_newer(metric, existing.checked_at, existing.metric_id):
                continue
            streak_started_at = _next_uptime_streak_started_at(
                existing=existing,
                latest_metric=metric,
                ordered_metric_batch=sorted(grouped_metrics[key], key=lambda item: (item.checked_at, int(item.id))),
            )
            if existing is None:
                self.db.add(
                    LatestMetric(
                        metric_id=int(metric.id),
                        device_id=int(metric.device_id),
                        metric_name=str(metric.metric_name),
                        metric_value=str(metric.metric_value),
                        metric_value_numeric=metric.metric_value_numeric,
                        status=metric.status,
                        unit=metric.unit,
                        checked_at=metric.checked_at,
                        uptime_streak_started_at=streak_started_at,
                    )
                )
                continue
            existing.metric_id = int(metric.id)
            existing.metric_value = str(metric.metric_value)
            existing.metric_value_numeric = metric.metric_value_numeric
            existing.status = metric.status
            existing.unit = metric.unit
            existing.checked_at = metric.checked_at
            existing.uptime_streak_started_at = streak_started_at

        await self.db.flush()
