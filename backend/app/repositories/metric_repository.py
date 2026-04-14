from collections.abc import Iterable

from sqlalchemy import Select, and_, case, desc, distinct, func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.device import Device
from ..models.metric import Metric


class MetricRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

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
        query = (
            select(
                Metric.id,
                Metric.device_id,
                Device.name.label("device_name"),
                Metric.metric_name,
                Metric.metric_value,
                Metric.status,
                Metric.unit,
                Metric.checked_at,
            )
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
        query = query.order_by(desc(Metric.checked_at), desc(Metric.id)).offset(offset).limit(limit)
        rows = (await self.db.execute(query)).all()
        return [
            {
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
            for row in rows
        ]

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
        ranked_metrics = (
            select(
                Metric.id.label("metric_id"),
                func.row_number()
                .over(
                    partition_by=(Metric.device_id, Metric.metric_name),
                    order_by=(desc(Metric.checked_at), desc(Metric.id)),
                )
                .label("row_number"),
            )
            .subquery()
        )
        query = (
            select(
                Metric.id,
                Metric.device_id,
                Device.name.label("device_name"),
                Metric.metric_name,
                Metric.metric_value,
                Metric.status,
                Metric.unit,
                Metric.checked_at,
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
        rows = (await self.db.execute(query)).all()
        return [
            {
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
            for row in rows
        ]

    async def list_latest_metrics(self) -> list[Metric]:
        ranked_metrics = (
            select(
                Metric.id,
                func.row_number()
                .over(
                    partition_by=(Metric.device_id, Metric.metric_name),
                    order_by=(desc(Metric.checked_at), desc(Metric.id)),
                )
                .label("row_number"),
            )
            .subquery()
        )
        latest_metric = aliased(Metric)
        query = (
            select(latest_metric)
            .join(ranked_metrics, latest_metric.id == ranked_metrics.c.id)
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
        ranked_metrics = (
            select(
                Metric.id,
                func.row_number()
                .over(
                    partition_by=(Metric.device_id, Metric.metric_name),
                    order_by=(desc(Metric.checked_at), desc(Metric.id)),
                )
                .label("row_number"),
            )
            .subquery()
        )
        query = select(func.count()).select_from(ranked_metrics).where(ranked_metrics.c.row_number == 1)
        return int(await self.db.scalar(query) or 0)

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
