"""Provide database query and persistence repositories for the network monitoring project."""

from collections.abc import Iterable

from sqlalchemy import Select, and_, case, desc, distinct, func, select, tuple_
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.device import Device
from ..models.latest_metric import LatestMetric
from ..models.metric import Metric
from ..models.metric_daily_rollup import MetricDailyRollup


UP_STATUSES = {"up", "ok"}


class MetricRepository:
    """Represent metric repository behavior and data for database query and persistence repositories.
    """
    def __init__(self, db: AsyncSession):
        """Handle the internal init helper logic for database query and persistence repositories.

        Args:
            db: db value used by this routine (type `AsyncSession`).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        self.db = db

    @staticmethod
    def _metric_row_payload(row) -> dict:
        """Handle the internal metric row payload helper logic for database query and persistence repositories.

        Args:
            row: row value used by this routine.

        Returns:
            `dict` result produced by the routine.
        """
        metric_value_numeric = row.metric_value_numeric
        if metric_value_numeric is None:
            metric_value_numeric = _safe_float(row.metric_value)
        return {
            "id": row.id,
            "device_id": row.device_id,
            "device_name": row.device_name or "Unknown Device",
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
            "metric_value_numeric": metric_value_numeric,
            "status": row.status,
            "unit": row.unit,
            "checked_at": row.checked_at,
        }

    @staticmethod
    def _normalize_metric_names(metric_names: list[str] | None) -> list[str]:
        """Normalize metric names for database query and persistence repositories.

        Args:
            metric_names: metric names value used by this routine (type `list[str] | None`).

        Returns:
            `list[str]` result produced by the routine.
        """
        if not metric_names:
            return []
        return list(dict.fromkeys(str(metric_name) for metric_name in metric_names if metric_name))

    @staticmethod
    def _recent_metric_filter_conditions(
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ) -> list[object]:
        """Handle the internal recent metric filter conditions helper logic for database query and persistence repositories.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            metric_name: metric name keyword value used by this routine (type `str | None`, optional).
            metric_names: metric names keyword value used by this routine (type `list[str] | None`, optional).
            status: status keyword value used by this routine (type `str | None`, optional).
            checked_from: checked from keyword value used by this routine (optional).
            checked_to: checked to keyword value used by this routine (optional).

        Returns:
            `list[object]` result produced by the routine.
        """
        conditions: list[object] = []
        if device_id is not None:
            conditions.append(Metric.device_id == device_id)
        if metric_name:
            conditions.append(Metric.metric_name == metric_name)
        elif metric_names:
            normalized_metric_names = MetricRepository._normalize_metric_names(metric_names)
            if normalized_metric_names:
                conditions.append(Metric.metric_name.in_(normalized_metric_names))
        if status:
            conditions.append(Metric.status == status)
        if checked_from is not None:
            conditions.append(Metric.checked_at >= checked_from)
        if checked_to is not None:
            conditions.append(Metric.checked_at <= checked_to)
        return conditions

    def _recent_metric_rows_query(
        self,
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ):
        """Handle the internal recent metric rows query helper logic for database query and persistence repositories.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            metric_name: metric name keyword value used by this routine (type `str | None`, optional).
            metric_names: metric names keyword value used by this routine (type `list[str] | None`, optional).
            status: status keyword value used by this routine (type `str | None`, optional).
            checked_from: checked from keyword value used by this routine (optional).
            checked_to: checked to keyword value used by this routine (optional).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        query = (
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
            .outerjoin(Device, Device.id == Metric.device_id)
        )
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
        return query

    async def create_metrics(self, payloads: Iterable[dict]) -> list[Metric]:
        """Create metrics for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            payloads: payloads value used by this routine (type `Iterable[dict]`).

        Returns:
            `list[Metric]` result produced by the routine.
        """
        metrics = [
            Metric(
                **payload,
                metric_value_numeric=payload.get("metric_value_numeric", _safe_float(payload.get("metric_value"))),
            )
            for payload in payloads
        ]
        if not metrics:
            return []

        self.db.add_all(metrics)
        await self.db.flush()
        await self._upsert_latest_metrics(metrics)
        await self.db.commit()
        return metrics

    async def _upsert_latest_metrics(self, metrics: list[Metric]) -> None:
        """Handle the internal upsert latest metrics helper logic for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            metrics: metrics value used by this routine (type `list[Metric]`).

        Returns:
            None. The routine is executed for its side effects.
        """
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
        for chunk in _chunked(keys, 250):
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

    async def list_recent_metrics(
        self,
        limit: int = 100,
        device_id: int | None = None,
        metric_name: str | None = None,
        status: str | None = None,
    ) -> list[Metric]:
        """Return a list of recent metrics for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit value used by this routine (type `int`, optional).
            device_id: device id value used by this routine (type `int | None`, optional).
            metric_name: metric name value used by this routine (type `str | None`, optional).
            status: status value used by this routine (type `str | None`, optional).

        Returns:
            `list[Metric]` result produced by the routine.
        """
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
        """Return a list of recent metrics by device for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_ids: device ids keyword value used by this routine (type `list[int]`).
            metric_name: metric name keyword value used by this routine (type `str`).
            per_device_limit: per device limit keyword value used by this routine (type `int`, optional).

        Returns:
            `dict[int, list[Metric]]` result produced by the routine.
        """
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
        offset: int = 0,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ) -> list[dict]:
        """Return a list of recent metric rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit value used by this routine (type `int`, optional).
            offset: offset value used by this routine (type `int`, optional).
            device_id: device id value used by this routine (type `int | None`, optional).
            metric_name: metric name value used by this routine (type `str | None`, optional).
            metric_names: metric names value used by this routine (type `list[str] | None`, optional).
            status: status value used by this routine (type `str | None`, optional).
            checked_from: checked from value used by this routine (optional).
            checked_to: checked to value used by this routine (optional).

        Returns:
            `list[dict]` result produced by the routine.
        """
        query = self._recent_metric_rows_query(
            device_id=device_id,
            metric_name=metric_name,
            metric_names=metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        rows = (
            await self.db.execute(
                query.order_by(desc(Metric.checked_at), desc(Metric.id)).offset(offset).limit(limit)
            )
        ).all()
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
        checked_from=None,
        checked_to=None,
    ) -> tuple[list[dict], int]:
        """Return a list of recent metric rows paged for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit keyword value used by this routine (type `int`, optional).
            offset: offset keyword value used by this routine (type `int`, optional).
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            metric_name: metric name keyword value used by this routine (type `str | None`, optional).
            metric_names: metric names keyword value used by this routine (type `list[str] | None`, optional).
            per_metric_limit: per metric limit keyword value used by this routine (type `int | None`, optional).
            status: status keyword value used by this routine (type `str | None`, optional).
            checked_from: checked from keyword value used by this routine (optional).
            checked_to: checked to keyword value used by this routine (optional).

        Returns:
            `tuple[list[dict], int]` result produced by the routine.
        """
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

    async def _list_recent_metric_rows_per_metric_limit(
        self,
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str],
        per_metric_limit: int,
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ) -> tuple[list[dict], int]:
        """Return a list of recent metric rows per metric limit for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            metric_name: metric name keyword value used by this routine (type `str | None`, optional).
            metric_names: metric names keyword value used by this routine (type `list[str]`).
            per_metric_limit: per metric limit keyword value used by this routine (type `int`).
            status: status keyword value used by this routine (type `str | None`, optional).
            checked_from: checked from keyword value used by this routine (optional).
            checked_to: checked to keyword value used by this routine (optional).

        Returns:
            `tuple[list[dict], int]` result produced by the routine.
        """
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
        checked_from=None,
        checked_to=None,
    ) -> int:
        """Count recent metric rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            metric_name: metric name keyword value used by this routine (type `str | None`, optional).
            metric_names: metric names keyword value used by this routine (type `list[str] | None`, optional).
            status: status keyword value used by this routine (type `str | None`, optional).
            checked_from: checked from keyword value used by this routine (optional).
            checked_to: checked to keyword value used by this routine (optional).

        Returns:
            `int` result produced by the routine.
        """
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

    @staticmethod
    def _latest_metrics_query(*, device_id: int | None = None):
        """Handle the internal latest metrics query helper logic for database query and persistence repositories.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        internet_target_name_priority = case(
            (
                and_(
                    Device.device_type == "internet_target",
                    func.lower(Device.name).like("%myrepublic%"),
                ),
                0,
            ),
            (
                and_(
                    Device.device_type == "internet_target",
                    func.lower(Device.name).like("%isp%"),
                ),
                1,
            ),
            (
                and_(
                    Device.device_type == "internet_target",
                    func.lower(Device.name).like("%mikrotik%"),
                ),
                3,
            ),
            (
                Device.device_type == "internet_target",
                2,
            ),
            else_=4,
        )
        device_type_priority = case(
            (Device.device_type == "internet_target", 0),
            (Device.device_type == "mikrotik", 1),
            (Device.device_type == "access_point", 2),
            else_=3,
        )
        query = (
            select(
                LatestMetric.metric_id.label("id"),
                LatestMetric.device_id,
                Device.name.label("device_name"),
                LatestMetric.metric_name,
                LatestMetric.metric_value,
                LatestMetric.metric_value_numeric,
                LatestMetric.status,
                LatestMetric.unit,
                LatestMetric.checked_at,
            )
            .outerjoin(Device, Device.id == LatestMetric.device_id)
        )
        if device_id is not None:
            query = query.where(LatestMetric.device_id == device_id)
        return query.order_by(
            device_type_priority.asc(),
            internet_target_name_priority.asc(),
            Device.name.asc(),
            LatestMetric.metric_name.asc(),
        )

    async def list_latest_metric_rows(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        device_id: int | None = None,
    ) -> list[dict]:
        """Return a list of latest metric rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit keyword value used by this routine (type `int`, optional).
            offset: offset keyword value used by this routine (type `int`, optional).
            device_id: device id keyword value used by this routine (type `int | None`, optional).

        Returns:
            `list[dict]` result produced by the routine.
        """
        rows = (await self.db.execute(self._latest_metrics_query(device_id=device_id).offset(offset).limit(limit))).all()
        return [self._metric_row_payload(row) for row in rows]

    async def list_latest_metric_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        device_id: int | None = None,
    ) -> tuple[list[dict], int]:
        """Return a list of latest metric rows paged for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit keyword value used by this routine (type `int`, optional).
            offset: offset keyword value used by this routine (type `int`, optional).
            device_id: device id keyword value used by this routine (type `int | None`, optional).

        Returns:
            `tuple[list[dict], int]` result produced by the routine.
        """
        rows = (await self.db.execute(self._latest_metrics_query(device_id=device_id).offset(offset).limit(limit))).all()
        payload = [self._metric_row_payload(row) for row in rows]
        if offset == 0 and len(payload) < limit:
            return payload, len(payload)
        if not payload and offset > 0:
            return payload, await self.count_latest_metrics(device_id=device_id)
        return payload, await self.count_latest_metrics(device_id=device_id)

    async def list_latest_metrics(self) -> list[Metric]:
        """Return a list of latest metrics for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `list[Metric]` result produced by the routine.
        """
        latest_metric = aliased(Metric)
        query = select(latest_metric).join(LatestMetric, latest_metric.id == LatestMetric.metric_id)
        return list((await self.db.scalars(query)).all())

    async def get_latest_metric(self, device_id: int, metric_name: str) -> Metric | None:
        """Return latest metric for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id value used by this routine (type `int`).
            metric_name: metric name value used by this routine (type `str`).

        Returns:
            `Metric | None` result produced by the routine.
        """
        query = (
            select(Metric)
            .join(LatestMetric, Metric.id == LatestMetric.metric_id)
            .where(
                LatestMetric.device_id == device_id,
                LatestMetric.metric_name == metric_name,
            )
            .limit(1)
        )
        return (await self.db.scalars(query)).first()

    async def latest_metric_map(self) -> dict[tuple[int, str], Metric]:
        """Handle latest metric map for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `dict[tuple[int, str], Metric]` result produced by the routine.
        """
        query = select(Metric).join(LatestMetric, Metric.id == LatestMetric.metric_id)
        metrics = list((await self.db.scalars(query)).all())
        return {(metric.device_id, metric.metric_name): metric for metric in metrics}

    async def latest_metric_map_for_device(self, device_id: int) -> dict[str, Metric]:
        """Handle latest metric map for device for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id value used by this routine (type `int`).

        Returns:
            `dict[str, Metric]` result produced by the routine.
        """
        query = (
            select(Metric)
            .join(LatestMetric, Metric.id == LatestMetric.metric_id)
            .where(LatestMetric.device_id == device_id)
        )
        metrics = list((await self.db.scalars(query)).all())
        return {metric.metric_name: metric for metric in metrics}

    async def count_latest_metrics(self, *, device_id: int | None = None) -> int:
        """Count latest metrics for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).

        Returns:
            `int` result produced by the routine.
        """
        query = select(func.count()).select_from(LatestMetric)
        if device_id is not None:
            query = query.where(LatestMetric.device_id == device_id)
        return int(await self.db.scalar(query) or 0)

    async def summarize_latest_snapshot_status_counts(self) -> dict[str, int]:
        """Summarize latest snapshot status counts for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `dict[str, int]` result produced by the routine.
        """
        rows = (
            await self.db.execute(
                select(
                    LatestMetric.device_id,
                    func.lower(func.coalesce(LatestMetric.status, "unknown")).label("status"),
                )
            )
        ).all()
        device_statuses: dict[int, list[str]] = {}
        for device_id, status in rows:
            device_statuses.setdefault(int(device_id), []).append(str(status or "unknown"))

        counts: dict[str, int] = {}
        for statuses in device_statuses.values():
            rolled_up = _rollup_statuses(statuses)
            counts[rolled_up] = counts.get(rolled_up, 0) + 1
        return counts

    def summarize_latest_snapshot_status_counts_for_rows(self, latest_rows: list[dict]) -> dict[str, int]:
        """Summarize latest snapshot status counts for rows for database query and persistence repositories.

        Args:
            latest_rows: latest rows value used by this routine (type `list[dict]`).

        Returns:
            `dict[str, int]` result produced by the routine.
        """
        device_statuses: dict[int, list[str]] = {}
        for row in latest_rows:
            device_id = int(row.get("device_id") or 0)
            status = str(row.get("status") or "unknown").lower()
            device_statuses.setdefault(device_id, []).append(status)

        counts: dict[str, int] = {}
        for statuses in device_statuses.values():
            rolled_up = _rollup_statuses(statuses)
            counts[rolled_up] = counts.get(rolled_up, 0) + 1
        return counts

    async def latest_snapshot_uptime_map(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, str]:
        """Handle latest snapshot uptime map for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit keyword value used by this routine (type `int`, optional).
            offset: offset keyword value used by this routine (type `int`, optional).

        Returns:
            `dict[str, str]` result produced by the routine.
        """
        latest_rows = await self.list_latest_metric_rows(limit=limit, offset=offset)
        return await self.latest_snapshot_uptime_map_for_rows(latest_rows)

    async def latest_snapshot_uptime_map_for_rows(
        self,
        latest_rows: list[dict],
    ) -> dict[str, str]:
        """Handle latest snapshot uptime map for rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            latest_rows: latest rows value used by this routine (type `list[dict]`).

        Returns:
            `dict[str, str]` result produced by the routine.
        """
        latest_pairs = [
            (int(row["device_id"]), str(row["metric_name"]), row["checked_at"], str(row.get("status") or "unknown"))
            for row in latest_rows
        ]
        if not latest_pairs:
            return {}

        up_pairs = [
            (device_id, metric_name)
            for device_id, metric_name, _checked_at, status in latest_pairs
            if status.lower() in UP_STATUSES
        ]
        if not up_pairs:
            return {
                f"{device_id}:{metric_name}": "-"
                for device_id, metric_name, _checked_at, _status in latest_pairs
            }

        streak_rows = (
            await self.db.execute(
                select(
                    LatestMetric.device_id,
                    LatestMetric.metric_name,
                    LatestMetric.checked_at,
                    LatestMetric.uptime_streak_started_at,
                )
                .where(tuple_(LatestMetric.device_id, LatestMetric.metric_name).in_(up_pairs))
            )
        ).all()
        streak_map = {
            (int(device_id), str(metric_name)): (checked_at, uptime_streak_started_at)
            for device_id, metric_name, checked_at, uptime_streak_started_at in streak_rows
        }

        payload: dict[str, str] = {}
        for device_id, metric_name, latest_checked_at, status in latest_pairs:
            key = f"{device_id}:{metric_name}"
            if status.lower() not in UP_STATUSES:
                payload[key] = "-"
                continue
            pair = streak_map.get((device_id, metric_name))
            if pair is None:
                payload[key] = "-"
                continue
            row_checked_at, streak_started_at = pair
            if streak_started_at is None:
                payload[key] = "-"
                continue
            effective_latest = row_checked_at if row_checked_at is not None else latest_checked_at
            payload[key] = str(int((effective_latest - streak_started_at).total_seconds()))
        return payload

    async def list_metric_names(self, device_id: int | None = None) -> list[str]:
        """Return a list of metric names for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id value used by this routine (type `int | None`, optional).

        Returns:
            `list[str]` result produced by the routine.
        """
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
        """Build the daily summary query for database query and persistence repositories.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            rollup_from: rollup from keyword value used by this routine (optional).
            rollup_to: rollup to keyword value used by this routine (optional).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
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
        """Return daily summary rows from rollups for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit keyword value used by this routine (type `int`, optional).
            offset: offset keyword value used by this routine (type `int`, optional).
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            rollup_from: rollup from keyword value used by this routine (optional).
            rollup_to: rollup to keyword value used by this routine (optional).

        Returns:
            `tuple[list[dict], int]` result produced by the routine.
        """
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
        """Count daily summary rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            rollup_from: rollup from keyword value used by this routine (optional).
            rollup_to: rollup to keyword value used by this routine (optional).

        Returns:
            `int` result produced by the routine.
        """
        query = select(func.count()).select_from(MetricDailyRollup)
        if device_id is not None:
            query = query.where(MetricDailyRollup.device_id == device_id)
        if rollup_from is not None:
            query = query.where(MetricDailyRollup.rollup_date >= rollup_from)
        if rollup_to is not None:
            query = query.where(MetricDailyRollup.rollup_date <= rollup_to)
        return int(await self.db.scalar(query) or 0)


def _safe_float(value: str | None) -> float | None:
    """Handle the internal safe float helper logic for database query and persistence repositories.

    Args:
        value: value value used by this routine (type `str | None`).

    Returns:
        `float | None` result produced by the routine.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_metric_newer(metric: Metric, existing_checked_at, existing_metric_id: int | None) -> bool:
    """Handle the internal is metric newer helper logic for database query and persistence repositories.

    Args:
        metric: metric value used by this routine (type `Metric`).
        existing_checked_at: existing checked at value used by this routine.
        existing_metric_id: existing metric id value used by this routine (type `int | None`).

    Returns:
        `bool` result produced by the routine.
    """
    if existing_checked_at is None:
        return True
    if metric.checked_at > existing_checked_at:
        return True
    if metric.checked_at < existing_checked_at:
        return False
    return int(metric.id) > int(existing_metric_id or 0)


def _next_uptime_streak_started_at(
    *,
    existing: LatestMetric | None,
    latest_metric: Metric,
    ordered_metric_batch: list[Metric],
):
    """Handle the internal next uptime streak started at helper logic for database query and persistence repositories.

    Args:
        existing: existing keyword value used by this routine (type `LatestMetric | None`).
        latest_metric: latest metric keyword value used by this routine (type `Metric`).
        ordered_metric_batch: ordered metric batch keyword value used by this routine (type `list[Metric]`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    status = str(latest_metric.status or "").lower()
    if status not in UP_STATUSES:
        return None
    last_non_up_index = -1
    for index, metric in enumerate(ordered_metric_batch):
        if str(metric.status or "").lower() not in UP_STATUSES:
            last_non_up_index = index
    if last_non_up_index >= 0:
        for metric in ordered_metric_batch[last_non_up_index + 1 :]:
            if str(metric.status or "").lower() in UP_STATUSES:
                return metric.checked_at
        return latest_metric.checked_at

    first_up_in_batch = next(
        (metric.checked_at for metric in ordered_metric_batch if str(metric.status or "").lower() in UP_STATUSES),
        latest_metric.checked_at,
    )
    if existing is None:
        return first_up_in_batch
    existing_status = str(existing.status or "").lower()
    if existing_status in UP_STATUSES and existing.uptime_streak_started_at is not None:
        return existing.uptime_streak_started_at
    return first_up_in_batch


def _rollup_statuses(statuses: list[str]) -> str:
    """Handle the internal rollup statuses helper logic for database query and persistence repositories.

    Args:
        statuses: statuses value used by this routine (type `list[str]`).

    Returns:
        `str` result produced by the routine.
    """
    normalized = [str(status).lower() for status in statuses if status]
    if not normalized:
        return "unknown"
    if any(status in {"down", "critical", "error"} for status in normalized):
        return "down"
    if any(status in {"warning", "degraded", "unavailable"} for status in normalized):
        return "warning"
    if all(status in {"up", "healthy", "ok"} for status in normalized):
        return "up"
    return normalized[0]


def _chunked(items: list[tuple[int, str]], size: int):
    """Handle the internal chunked helper logic for database query and persistence repositories.

    Args:
        items: items value used by this routine (type `list[tuple[int, str]]`).
        size: size value used by this routine (type `int`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    for index in range(0, len(items), size):
        yield items[index : index + size]
