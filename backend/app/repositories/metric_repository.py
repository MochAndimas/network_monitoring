from collections.abc import Iterable

from sqlalchemy import Select, and_, case, desc, distinct, func, select, tuple_
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.device import Device
from ..models.metric import Metric


class MetricRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _latest_metrics_ranked_subquery():
        return (
            select(
                Metric.id.label("metric_id"),
                Metric.device_id.label("device_id"),
                Metric.metric_name.label("metric_name"),
                func.row_number()
                .over(
                    partition_by=(Metric.device_id, Metric.metric_name),
                    order_by=(desc(Metric.checked_at), desc(Metric.id)),
                )
                .label("row_number"),
            )
            .subquery()
        )

    @staticmethod
    def _metric_row_payload(row) -> dict:
        return {
            "id": row.id,
            "device_id": row.device_id,
            "device_name": row.device_name or "Unknown Device",
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
            "metric_value_numeric": _safe_float(row.metric_value),
            "status": row.status,
            "unit": row.unit,
            "checked_at": row.checked_at,
        }

    def _recent_metric_rows_query(
        self,
        *,
        include_total_count: bool = False,
        device_id: int | None = None,
        metric_name: str | None = None,
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ):
        columns = [
            Metric.id,
            Metric.device_id,
            Device.name.label("device_name"),
            Metric.metric_name,
            Metric.metric_value,
            Metric.status,
            Metric.unit,
            Metric.checked_at,
        ]
        if include_total_count:
            columns.append(func.count().over().label("total_count"))
        query = (
            select(*columns)
            .outerjoin(Device, Device.id == Metric.device_id)
        )
        if device_id is not None:
            query = query.where(Metric.device_id == device_id)
        if metric_name:
            query = query.where(Metric.metric_name == metric_name)
        if status:
            query = query.where(Metric.status == status)
        if checked_from is not None:
            query = query.where(Metric.checked_at >= checked_from)
        if checked_to is not None:
            query = query.where(Metric.checked_at <= checked_to)
        return query

    async def create_metrics(self, payloads: Iterable[dict]) -> list[Metric]:
        metrics = [Metric(**payload) for payload in payloads]
        if not metrics:
            return []

        self.db.add_all(metrics)
        await self.db.flush()
        await self.db.commit()
        return metrics

    async def list_recent_metrics(
        self,
        limit: int = 100,
        device_id: int | None = None,
        metric_name: str | None = None,
        status: str | None = None,
    ) -> list[Metric]:
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
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ) -> list[dict]:
        query = self._recent_metric_rows_query(
            device_id=device_id,
            metric_name=metric_name,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        query = query.order_by(desc(Metric.checked_at), desc(Metric.id)).offset(offset).limit(limit)
        rows = (await self.db.execute(query)).all()
        return [self._metric_row_payload(row) for row in rows]

    async def list_recent_metric_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        device_id: int | None = None,
        metric_name: str | None = None,
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ) -> tuple[list[dict], int]:
        query = self._recent_metric_rows_query(
            include_total_count=True,
            device_id=device_id,
            metric_name=metric_name,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        rows = (
            await self.db.execute(
                query.order_by(desc(Metric.checked_at), desc(Metric.id)).offset(offset).limit(limit)
            )
        ).all()
        total = int(rows[0].total_count) if rows else 0
        return [self._metric_row_payload(row) for row in rows], total

    async def count_recent_metric_rows(
        self,
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        status: str | None = None,
        checked_from=None,
        checked_to=None,
    ) -> int:
        query = select(func.count()).select_from(Metric)
        if device_id is not None:
            query = query.where(Metric.device_id == device_id)
        if metric_name:
            query = query.where(Metric.metric_name == metric_name)
        if status:
            query = query.where(Metric.status == status)
        if checked_from is not None:
            query = query.where(Metric.checked_at >= checked_from)
        if checked_to is not None:
            query = query.where(Metric.checked_at <= checked_to)
        return int(await self.db.scalar(query) or 0)

    async def list_latest_metric_rows(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
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
        ranked_metrics = self._latest_metrics_ranked_subquery()
        columns = [
            Metric.id,
            Metric.device_id,
            Device.name.label("device_name"),
            Metric.metric_name,
            Metric.metric_value,
            Metric.status,
            Metric.unit,
            Metric.checked_at,
        ]
        query = (
            select(*columns)
            .join(ranked_metrics, Metric.id == ranked_metrics.c.metric_id)
            .outerjoin(Device, Device.id == Metric.device_id)
            .where(ranked_metrics.c.row_number == 1)
            .order_by(
                device_type_priority.asc(),
                internet_target_name_priority.asc(),
                Device.name.asc(),
                Metric.metric_name.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.db.execute(query)).all()
        return [self._metric_row_payload(row) for row in rows]

    async def list_latest_metric_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
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
        ranked_metrics = self._latest_metrics_ranked_subquery()
        rows = (
            await self.db.execute(
                select(
                    Metric.id,
                    Metric.device_id,
                    Device.name.label("device_name"),
                    Metric.metric_name,
                    Metric.metric_value,
                    Metric.status,
                    Metric.unit,
                    Metric.checked_at,
                    func.count().over().label("total_count"),
                )
                .join(ranked_metrics, Metric.id == ranked_metrics.c.metric_id)
                .outerjoin(Device, Device.id == Metric.device_id)
                .where(ranked_metrics.c.row_number == 1)
                .order_by(
                    device_type_priority.asc(),
                    internet_target_name_priority.asc(),
                    Device.name.asc(),
                    Metric.metric_name.asc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        total = int(rows[0].total_count) if rows else 0
        return [self._metric_row_payload(row) for row in rows], total

    async def list_latest_metrics(self) -> list[Metric]:
        ranked_metrics = self._latest_metrics_ranked_subquery()
        latest_metric = aliased(Metric)
        query = (
            select(latest_metric)
            .join(ranked_metrics, latest_metric.id == ranked_metrics.c.metric_id)
            .where(ranked_metrics.c.row_number == 1)
        )
        return list((await self.db.scalars(query)).all())

    async def get_latest_metric(self, device_id: int, metric_name: str) -> Metric | None:
        query: Select[tuple[Metric]] = (
            select(Metric)
            .where(
                Metric.device_id == device_id,
                Metric.metric_name == metric_name,
            )
            .order_by(desc(Metric.checked_at), desc(Metric.id))
            .limit(1)
        )
        return (await self.db.scalars(query)).first()

    async def latest_metric_map(self) -> dict[tuple[int, str], Metric]:
        return {(metric.device_id, metric.metric_name): metric for metric in await self.list_latest_metrics()}

    async def count_latest_metrics(self) -> int:
        ranked_metrics = self._latest_metrics_ranked_subquery()
        query = select(func.count()).select_from(ranked_metrics).where(ranked_metrics.c.row_number == 1)
        return int(await self.db.scalar(query) or 0)

    async def summarize_latest_snapshot_status_counts(self) -> dict[str, int]:
        ranked_metrics = self._latest_metrics_ranked_subquery()
        query = (
            select(
                ranked_metrics.c.device_id,
                func.coalesce(Metric.status, "unknown").label("status"),
            )
            .join(Metric, Metric.id == ranked_metrics.c.metric_id)
            .where(ranked_metrics.c.row_number == 1)
        )
        rows = (await self.db.execute(query)).all()
        device_statuses: dict[int, list[str]] = {}
        for device_id, status in rows:
            device_statuses.setdefault(int(device_id), []).append(str(status or "unknown"))

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
        latest_rows = await self.list_latest_metric_rows(limit=limit, offset=offset)
        return await self.latest_snapshot_uptime_map_for_rows(latest_rows)

    async def latest_snapshot_uptime_map_for_rows(
        self,
        latest_rows: list[dict],
    ) -> dict[str, str]:
        latest_pairs = [
            (int(row["device_id"]), str(row["metric_name"]), row["checked_at"], str(row.get("status") or "unknown"))
            for row in latest_rows
        ]
        if not latest_pairs:
            return {}

        up_pairs = [
            (device_id, metric_name)
            for device_id, metric_name, _checked_at, status in latest_pairs
            if status.lower() in {"up", "ok"}
        ]
        if not up_pairs:
            return {
                f"{device_id}:{metric_name}": "-"
                for device_id, metric_name, _checked_at, _status in latest_pairs
            }

        uptime_rows = await self._latest_consecutive_up_rows(up_pairs)
        oldest_up_map = {
            (int(device_id), str(metric_name)): checked_at
            for device_id, metric_name, checked_at in uptime_rows
        }
        payload: dict[str, str] = {}
        for device_id, metric_name, latest_checked_at, status in latest_pairs:
            key = f"{device_id}:{metric_name}"
            if status.lower() not in {"up", "ok"}:
                payload[key] = "-"
                continue
            oldest_checked_at = oldest_up_map.get((device_id, metric_name))
            if oldest_checked_at is None:
                payload[key] = "-"
                continue
            payload[key] = str(int((latest_checked_at - oldest_checked_at).total_seconds()))
        return payload

    async def _latest_consecutive_up_rows(self, pairs: list[tuple[int, str]]) -> list[tuple[int, str, object]]:
        ordered_metrics = (
            select(
                Metric.device_id.label("device_id"),
                Metric.metric_name.label("metric_name"),
                Metric.checked_at.label("checked_at"),
                Metric.status.label("status"),
                Metric.id.label("id"),
                func.sum(
                    case(
                        (func.lower(func.coalesce(Metric.status, "unknown")).in_(["up", "ok"]), 0),
                        else_=1,
                    )
                )
                .over(
                    partition_by=(Metric.device_id, Metric.metric_name),
                    order_by=(desc(Metric.checked_at), desc(Metric.id)),
                )
                .label("non_up_seen"),
            )
            .where(tuple_(Metric.device_id, Metric.metric_name).in_(pairs))
            .subquery()
        )
        query = (
            select(
                ordered_metrics.c.device_id,
                ordered_metrics.c.metric_name,
                func.min(ordered_metrics.c.checked_at).label("oldest_checked_at"),
            )
            .where(
                ordered_metrics.c.non_up_seen == 0,
                func.lower(func.coalesce(ordered_metrics.c.status, "unknown")).in_(["up", "ok"]),
            )
            .group_by(ordered_metrics.c.device_id, ordered_metrics.c.metric_name)
        )
        return list((await self.db.execute(query)).all())

    async def list_metric_names(self, device_id: int | None = None) -> list[str]:
        query = select(distinct(Metric.metric_name)).order_by(Metric.metric_name)
        if device_id is not None:
            query = query.where(Metric.device_id == device_id)
        return list((await self.db.scalars(query)).all())


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rollup_statuses(statuses: list[str]) -> str:
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
