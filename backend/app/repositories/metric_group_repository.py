"""Queries scoped to a bounded page of active monitoring-group devices."""

from datetime import datetime
from typing import Any

from sqlalchemy import Select, desc, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ..models.device import Device
from ..models.latest_metric import LatestMetric
from ..models.metric import Metric
from .metrics.alert_history import ALERT_HISTORY_PAIR_BATCH_SIZE

VALUE_CHAR_LIMIT = 256


def group_device_query(
    *, group: str, site: str | None, device_type: str | None, device_id: int | None
) -> Select[tuple[Device]]:
    query = select(Device).where(Device.is_active.is_(True))
    if group == "voip":
        query = query.where(func.lower(Device.device_type) == "voip")
    elif group == "ruijie":
        query = query.where(or_(func.lower(Device.device_type) == "ruijie", func.lower(Device.name).contains("ruijie")))
    else:
        raise ValueError("Unsupported monitoring group")
    if site is not None:
        query = query.where(Device.site == site)
    if device_type is not None:
        query = query.where(Device.device_type == device_type)
    if device_id is not None:
        query = query.where(Device.id == device_id)
    return query


def metric_columns(model: type[Metric] | type[LatestMetric]) -> list[ColumnElement[Any]]:
    return [
        (LatestMetric.metric_id if model is LatestMetric else Metric.id).label("id"),
        model.device_id.label("device_id"),
        Device.name.label("device_name"),
        model.metric_name.label("metric_name"),
        func.substr(model.metric_value, 1, VALUE_CHAR_LIMIT).label("metric_value"),
        model.metric_value_numeric.label("metric_value_numeric"),
        model.status.label("status"),
        model.unit.label("unit"),
        model.checked_at.label("checked_at"),
    ]


class MetricGroupRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def devices(
        self, *, group: str, site: str | None, device_type: str | None, device_id: int | None, limit: int, offset: int
    ) -> tuple[list[Device], int]:
        query = group_device_query(group=group, site=site, device_type=device_type, device_id=device_id)
        total = int(await self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        devices = list((await self.db.scalars(query.order_by(Device.id).offset(offset).limit(limit))).all())
        return devices, total

    async def metric_names(self, device_ids: list[int]) -> list[str]:
        return list(
            (
                await self.db.scalars(
                    select(LatestMetric.metric_name)
                    .where(LatestMetric.device_id.in_(device_ids))
                    .distinct()
                    .order_by(LatestMetric.metric_name)
                    .limit(65)
                )
            ).all()
        )

    async def health(self, device_ids: list[int]) -> dict[int, tuple[datetime, str]]:
        rows = (
            await self.db.execute(
                select(LatestMetric.device_id, LatestMetric.checked_at, LatestMetric.status).where(
                    LatestMetric.device_id.in_(device_ids), LatestMetric.metric_name == "ping"
                )
            )
        ).all()
        latest_times = (
            await self.db.execute(
                select(LatestMetric.device_id, func.max(LatestMetric.checked_at).label("checked_at"))
                .where(LatestMetric.device_id.in_(device_ids))
                .group_by(LatestMetric.device_id)
            )
        ).all()
        result = {row.device_id: (row.checked_at, "unknown") for row in latest_times}
        result.update({row.device_id: (row.checked_at, row.status or "unknown") for row in rows})
        return result

    async def section(
        self,
        *,
        device_ids: list[int],
        snapshot: bool,
        metric_name: str | None,
        status: str | None,
        checked_from: datetime,
        checked_to: datetime,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        model = LatestMetric if snapshot else Metric
        filters: list[ColumnElement[bool]] = [model.device_id.in_(device_ids)]
        if metric_name:
            filters.append(model.metric_name == metric_name)
        if status:
            filters.append(model.status == status)
        if not snapshot:
            filters.extend([model.checked_at >= checked_from, model.checked_at <= checked_to])
        query = select(*metric_columns(model)).join(Device, Device.id == model.device_id).where(*filters)
        rows = list(
            (
                await self.db.execute(
                    query.order_by(
                        desc(model.checked_at),
                        desc(model.device_id),
                        desc(model.metric_name),
                        desc(LatestMetric.metric_id if snapshot else Metric.id),
                    )
                    .limit(limit + 1)
                    .offset(offset)
                )
            )
            .mappings()
            .all()
        )
        total = (
            int(await self.db.scalar(select(func.count()).select_from(model).where(*filters)) or 0)
            if snapshot
            else len(rows[:limit])
        )
        return [dict(row) for row in rows[:limit]], total, len(rows) > limit

    async def trends(
        self,
        *,
        device_ids: list[int],
        metric_names: list[str],
        status: str | None,
        checked_from: datetime,
        checked_to: datetime,
        samples: int,
    ) -> tuple[list[dict], bool]:
        pairs = [(device_id, name) for device_id in device_ids for name in metric_names]
        items: list[dict] = []
        sampled = False
        for offset in range(0, len(pairs), ALERT_HISTORY_PAIR_BATCH_SIZE):
            branches = []
            for device_id, name in pairs[offset : offset + ALERT_HISTORY_PAIR_BATCH_SIZE]:
                query = select(Metric.id).where(
                    Metric.device_id == device_id,
                    Metric.metric_name == name,
                    Metric.checked_at >= checked_from,
                    Metric.checked_at <= checked_to,
                )
                if status:
                    query = query.where(Metric.status == status)
                ids = query.order_by(desc(Metric.checked_at), desc(Metric.id)).limit(samples + 1).subquery()
                branches.append(select(ids.c.id))
            selected = union_all(*branches).subquery()
            rows = (
                (
                    await self.db.execute(
                        select(*metric_columns(Metric))
                        .join(selected, Metric.id == selected.c.id)
                        .join(Device, Device.id == Metric.device_id)
                        .order_by(Metric.device_id, Metric.metric_name, desc(Metric.checked_at), desc(Metric.id))
                    )
                )
                .mappings()
                .all()
            )
            counts: dict[tuple[int, str], int] = {}
            for row in rows:
                key = (row["device_id"], row["metric_name"])
                counts[key] = counts.get(key, 0) + 1
                if counts[key] <= samples:
                    items.append(dict(row))
                else:
                    sampled = True
        return items, sampled
