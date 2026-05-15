"""Latest metric snapshot query operations."""

from sqlalchemy import and_, case, desc, func, or_, select, tuple_
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from .base import MetricRepositoryBase
from ...models.device import Device
from ...models.latest_metric import LatestMetric
from ...models.metric import Metric
from .helpers import UP_STATUSES, _rollup_statuses


class MetricLatestMixin(MetricRepositoryBase):
    """Latest-snapshot metric repository methods."""

    @staticmethod
    def _latest_metric_sort_columns():
        """Return stable sort expressions shared by latest-snapshot pagination paths."""
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
        device_name_sort = func.coalesce(Device.name, "")
        metric_name_sort = func.coalesce(LatestMetric.metric_name, "")
        return (
            device_type_priority,
            internet_target_name_priority,
            device_name_sort,
            metric_name_sort,
            LatestMetric.metric_id,
        )

    @staticmethod
    def _latest_metrics_query(*, device_id: int | None = None):
        """Return latest latest metrics query used by metric collection and history."""
        (
            device_type_priority,
            internet_target_name_priority,
            device_name_sort,
            metric_name_sort,
            metric_id_sort,
        ) = MetricLatestMixin._latest_metric_sort_columns()
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
                device_type_priority.label("sort_device_type_priority"),
                internet_target_name_priority.label("sort_internet_target_name_priority"),
                device_name_sort.label("sort_device_name"),
                metric_name_sort.label("sort_metric_name"),
            )
            .outerjoin(Device, Device.id == LatestMetric.device_id)
        )
        if device_id is not None:
            query = query.where(LatestMetric.device_id == device_id)
        return query.order_by(
            device_type_priority.asc(),
            internet_target_name_priority.asc(),
            device_name_sort.asc(),
            metric_name_sort.asc(),
            metric_id_sort.asc(),
        )

    async def list_latest_metric_rows(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        device_id: int | None = None,
    ) -> list[dict]:
        """Return latest snapshot rows in API dictionary form."""
        rows = (await self.db.execute(self._latest_metrics_query(device_id=device_id).offset(offset).limit(limit))).all()
        return [self._metric_row_payload(row) for row in rows]

    async def list_latest_metric_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        device_id: int | None = None,
    ) -> tuple[list[dict], int]:
        """Return paginated latest snapshot rows and the matching total count."""
        rows = (await self.db.execute(self._latest_metrics_query(device_id=device_id).offset(offset).limit(limit))).all()
        payload = [self._metric_row_payload(row) for row in rows]
        if offset == 0 and len(payload) < limit:
            return payload, len(payload)
        if not payload and offset > 0:
            return payload, await self.count_latest_metrics(device_id=device_id)
        return payload, await self.count_latest_metrics(device_id=device_id)

    async def list_latest_metric_rows_after_cursor(
        self,
        *,
        limit: int = 100,
        cursor_payload: dict,
        device_id: int | None = None,
    ) -> tuple[list[dict], bool]:
        """Return the next latest-snapshot page using keyset pagination."""
        (
            device_type_priority,
            internet_target_name_priority,
            device_name_sort,
            metric_name_sort,
            metric_id_sort,
        ) = self._latest_metric_sort_columns()
        query = self._latest_metrics_query(device_id=device_id).where(
            or_(
                device_type_priority > cursor_payload["device_type_priority"],
                and_(
                    device_type_priority == cursor_payload["device_type_priority"],
                    internet_target_name_priority > cursor_payload["internet_target_name_priority"],
                ),
                and_(
                    device_type_priority == cursor_payload["device_type_priority"],
                    internet_target_name_priority == cursor_payload["internet_target_name_priority"],
                    device_name_sort > cursor_payload["device_name"],
                ),
                and_(
                    device_type_priority == cursor_payload["device_type_priority"],
                    internet_target_name_priority == cursor_payload["internet_target_name_priority"],
                    device_name_sort == cursor_payload["device_name"],
                    metric_name_sort > cursor_payload["metric_name"],
                ),
                and_(
                    device_type_priority == cursor_payload["device_type_priority"],
                    internet_target_name_priority == cursor_payload["internet_target_name_priority"],
                    device_name_sort == cursor_payload["device_name"],
                    metric_name_sort == cursor_payload["metric_name"],
                    metric_id_sort > cursor_payload["id"],
                ),
            )
        )
        rows = (await self.db.execute(query.limit(limit + 1))).all()
        has_more = len(rows) > limit
        return [self._metric_row_payload(row) for row in rows[:limit]], has_more

    async def list_latest_metrics(self) -> list[Metric]:
        """Return ORM metric rows referenced by the latest snapshot table."""
        latest_metric = aliased(Metric)
        query = select(latest_metric).join(LatestMetric, latest_metric.id == LatestMetric.metric_id)
        return list((await self.db.scalars(query)).all())

    async def get_latest_metric(self, device_id: int, metric_name: str) -> Metric | None:
        """Return get latest metric used by metric collection and history."""
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

    async def get_latest_valid_public_ip_metric(self, device_id: int) -> Metric | None:
        """Return the latest successful public IP sample for change detection."""
        query = (
            select(Metric)
            .where(
                Metric.device_id == device_id,
                Metric.metric_name == "public_ip",
                Metric.metric_value != "unavailable",
                Metric.status.in_(("up", "warning")),
            )
            .order_by(desc(Metric.checked_at), desc(Metric.id))
            .limit(1)
        )
        return (await self.db.scalars(query)).first()

    async def latest_metric_map(self) -> dict[tuple[int, str], Metric]:
        """Return latest latest metric map used by metric collection and history."""
        query = select(Metric).join(LatestMetric, Metric.id == LatestMetric.metric_id)
        metrics = list((await self.db.scalars(query)).all())
        return {(metric.device_id, metric.metric_name): metric for metric in metrics}

    async def latest_metric_map_for_alert_evaluation(
        self,
        *,
        exact_metric_names: set[str],
        dynamic_metric_name_patterns: tuple[str, ...],
    ) -> dict[tuple[int, str], Metric]:
        """Return latest metrics referenced by alert evaluation rules."""
        conditions: list[ColumnElement[bool]] = []
        if exact_metric_names:
            conditions.append(LatestMetric.metric_name.in_(exact_metric_names))
        conditions.extend(LatestMetric.metric_name.like(pattern) for pattern in dynamic_metric_name_patterns)

        query = (
            select(Metric)
            .join(LatestMetric, Metric.id == LatestMetric.metric_id)
            .join(Device, Device.id == LatestMetric.device_id)
            .where(Device.is_active.is_(True))
        )
        if conditions:
            query = query.where(or_(*conditions))
        metrics = list((await self.db.scalars(query)).all())
        return {(metric.device_id, metric.metric_name): metric for metric in metrics}

    async def latest_metric_map_for_device(self, device_id: int) -> dict[str, Metric]:
        """Return latest latest metric map for device used by metric collection and history."""
        query = (
            select(Metric)
            .join(LatestMetric, Metric.id == LatestMetric.metric_id)
            .where(LatestMetric.device_id == device_id)
        )
        metrics = list((await self.db.scalars(query)).all())
        return {metric.metric_name: metric for metric in metrics}

    async def count_latest_metrics(self, *, device_id: int | None = None) -> int:
        """Count latest metrics for metric repository queries."""
        query = select(func.count()).select_from(LatestMetric)
        if device_id is not None:
            query = query.where(LatestMetric.device_id == device_id)
        return int(await self.db.scalar(query) or 0)

    async def summarize_latest_snapshot_status_counts(self) -> dict[str, int]:
        """Summarize latest metric statuses into device-level health counts."""
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
        """Summarize latest snapshot status counts for rows for metric repository queries."""
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
        """Return latest latest snapshot uptime map used by metric collection and history."""
        latest_rows = await self.list_latest_metric_rows(limit=limit, offset=offset)
        return await self.latest_snapshot_uptime_map_for_rows(latest_rows)

    async def latest_snapshot_uptime_map_for_rows(
        self,
        latest_rows: list[dict],
    ) -> dict[str, str]:
        """Return latest latest snapshot uptime map for rows used by metric collection and history."""
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
