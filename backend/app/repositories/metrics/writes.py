"""Metric write and latest-snapshot update operations."""

import logging
from collections.abc import Iterable, Mapping
from time import perf_counter
from typing import Any
from uuid import uuid4
from shared.metric_contracts import MetricWritePayload

from shared.collection_utils import chunked
from shared.number_utils import safe_float
from sqlalchemy import event, select, tuple_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.engine.interfaces import ExecuteStyle
from sqlalchemy.orm.attributes import set_committed_value

from ...core.phase_timing import timed_phase
from ...core.time import now
from .base import MetricRepositoryBase
from ...models.latest_metric import LatestMetric
from ...models.metric import Metric
from ...models.device import Device
from .helpers import _is_metric_newer, _next_uptime_streak_started_at


logger = logging.getLogger("network_monitoring.metric_writes")
METRIC_INSERT_BATCH_SIZE = 500
METRIC_WRITE_FIELDS = frozenset(MetricWritePayload.__annotations__)


class MetricWriteMixin(MetricRepositoryBase):
    """Write-side metric repository methods."""

    async def create_metrics(
        self, payloads: Iterable[MetricWritePayload | Mapping[str, Any]], *, commit: bool = True
    ) -> list[Metric]:
        """Insert a batch of raw metrics and update the latest-metric snapshot table."""
        rows = [
            {
                **payload,
                "metric_value_numeric": payload.get("metric_value_numeric", safe_float(payload.get("metric_value"))),
            }
            for payload in payloads
        ]
        if not rows:
            return []

        # Lock existing parent rows before raw inserts acquire FK locks. This
        # serializes even the first snapshot insert, where no latest row exists.
        # Ordering keeps overlapping batches consistent; unrelated devices can
        # still be written concurrently. Locks last until transaction completion.
        with timed_phase(logger, "metric_device_row_lock", "metrics"):
            for device_ids in chunked(sorted({int(row["device_id"]) for row in rows}), 250):
                await self.db.execute(
                    select(Device.id).where(Device.id.in_(device_ids)).order_by(Device.id).with_for_update()
                )
        with timed_phase(logger, "metric_history_insert_flush", "metrics"):
            if self.db.get_bind().dialect.name == "mysql" and all(row.keys() <= METRIC_WRITE_FIELDS for row in rows):
                metrics = await self._bulk_insert_metric_history(rows)
            else:
                metrics = [Metric(**row) for row in rows]
                self.db.add_all(metrics)
                await self._flush_metric_history(len(metrics))
        with timed_phase(logger, "metric_snapshot_update", "metrics"):
            await self._upsert_latest_metrics(metrics)
        if commit:
            await self.db.commit()
        return metrics

    async def _bulk_insert_metric_history(self, rows: list[dict[str, Any]]) -> list[Metric]:
        # Preserve the ordering of pending inventory and other writes in this unit of work.
        await self.db.flush()
        connection = await self.db.connection()
        metrics: list[Metric] = []
        started_at = perf_counter()
        execute_calls = 0
        executemany_calls = 0
        for batch in chunked(rows, METRIC_INSERT_BATCH_SIZE):
            values = [
                {
                    "status": None,
                    "unit": None,
                    **row,
                    "checked_at": row.get("checked_at") or now(),
                    "insert_token": uuid4().bytes,
                }
                for row in batch
            ]
            await connection.execute(Metric.__table__.insert(), values)
            if len(values) == 1:
                execute_calls += 1
            else:
                executemany_calls += 1
            tokens = [value["insert_token"] for value in values]
            result = await self.db.scalars(select(Metric).where(Metric.insert_token.in_(tokens)))
            inserted = {metric.insert_token: metric for metric in result}
            for value in values:
                metric = inserted[value["insert_token"]]
                # ORM flush keeps input precision in memory even when MySQL
                # rounds DATETIME or FLOAT on storage. Snapshot ordering uses it.
                for field in ("checked_at", "metric_value_numeric"):
                    set_committed_value(metric, field, value[field])
                metrics.append(metric)
        logger.info(
            "metric_insert_profile metrics=%d execute_calls=%d executemany_calls=%d duration_ms=%.2f",
            len(metrics), execute_calls, executemany_calls, (perf_counter() - started_at) * 1000,
        )
        return metrics

    async def _flush_metric_history(self, metric_count: int) -> None:
        connection = (await self.db.connection()).sync_connection
        execute_calls = 0
        executemany_calls = 0

        def count_insert(
            conn: Connection,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: ExecutionContext,
            executemany: bool,
        ) -> None:
            nonlocal execute_calls, executemany_calls
            insert = context.compiled.statement if context.isinsert and context.compiled is not None else None
            if getattr(insert, "table", None) is not Metric.__table__:
                return
            # SQLAlchemy can mark an expanded insert as executemany even when
            # it dispatches a single cursor.execute call.
            if executemany and context.execute_style is ExecuteStyle.EXECUTEMANY:
                executemany_calls += 1
            else:
                execute_calls += 1

        started_at = perf_counter()
        event.listen(connection, "after_cursor_execute", count_insert)
        try:
            await self.db.flush()
        finally:
            event.remove(connection, "after_cursor_execute", count_insert)
            logger.info(
                "metric_insert_profile metrics=%d execute_calls=%d executemany_calls=%d duration_ms=%.2f",
                metric_count, execute_calls, executemany_calls, (perf_counter() - started_at) * 1000,
            )

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
        keys = sorted(grouped_metrics)
        if self.db.get_bind().dialect.name == "mysql":
            await self._ensure_mysql_latest_rows(grouped_metrics, latest_by_key)

        existing_rows: dict[tuple[int, str], LatestMetric] = {}
        for chunk in chunked(keys, 250):
            query = (
                select(LatestMetric)
                .where(tuple_(LatestMetric.device_id, LatestMetric.metric_name).in_(chunk))
                .with_hint(LatestMetric, "FORCE INDEX (uq_latest_metrics_device_metric)", dialect_name="mysql")
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            for row in (await self.db.scalars(query)).all():
                existing_rows[(int(row.device_id), str(row.metric_name))] = row

        for key, metric in latest_by_key.items():
            existing = existing_rows.get(key)
            if existing is not None and not _is_metric_newer(metric, existing.checked_at, existing.metric_id):
                continue
            streak_started_at = _next_uptime_streak_started_at(
                existing=existing,
                latest_metric=metric,
                ordered_metric_batch=sorted(
                    [
                        item
                        for item in grouped_metrics[key]
                        if existing is None or _is_metric_newer(item, existing.checked_at, existing.metric_id)
                    ],
                    key=lambda item: (item.checked_at, int(item.id)),
                ),
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

        with timed_phase(logger, "metric_snapshot_flush", "metrics"):
            await self.db.flush()

    async def _ensure_mysql_latest_rows(
        self,
        grouped_metrics: dict[tuple[int, str], list[Metric]],
        latest_by_key: dict[tuple[int, str], Metric],
    ) -> None:
        """Seed missing keys without replacing existing snapshot values.

        The parent-device locks are already held. The first non-locking read
        only avoids redundant inserts; correctness comes from the duplicate-key
        no-op and the subsequent current locking read, not this read view.
        """
        keys = sorted(grouped_metrics)
        # Materialize absent keys before the locking read. Reading missing
        # keys FOR UPDATE can take gap locks and deadlock independent devices.
        present_keys: set[tuple[int, str]] = set()
        for batch in chunked(keys, 250):
            rows = await self.db.execute(
                select(LatestMetric.device_id, LatestMetric.metric_name).where(
                    tuple_(LatestMetric.device_id, LatestMetric.metric_name).in_(batch)
                )
            )
            present_keys.update((int(device_id), str(metric_name)) for device_id, metric_name in rows)
        seeds = []
        for key in keys:
            if key in present_keys:
                continue
            metric = latest_by_key[key]
            seeds.append(
                dict(
                    metric_id=metric.id,
                    device_id=metric.device_id,
                    metric_name=metric.metric_name,
                    metric_value=metric.metric_value,
                    metric_value_numeric=metric.metric_value_numeric,
                    status=metric.status,
                    unit=metric.unit,
                    checked_at=metric.checked_at,
                    uptime_streak_started_at=_next_uptime_streak_started_at(
                        existing=None,
                        latest_metric=metric,
                        ordered_metric_batch=sorted(
                            grouped_metrics[key], key=lambda item: (item.checked_at, int(item.id))
                        ),
                    ),
                )
            )
        for seed_batch in chunked(seeds, 250):
            statement = mysql_insert(LatestMetric).values(seed_batch)
            await self.db.execute(statement.on_duplicate_key_update(metric_id=LatestMetric.metric_id))
