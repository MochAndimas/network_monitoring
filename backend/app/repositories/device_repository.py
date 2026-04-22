from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.device import Device
from ..models.alert import Alert
from ..models.incident import Incident
from ..models.latest_metric import LatestMetric
from ..models.metric import Metric
from ..models.metric_cold_archive import MetricColdArchive
from ..models.metric_daily_rollup import MetricDailyRollup


class DeviceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _latest_ping_metrics_subquery():
        return (
            select(
                LatestMetric.metric_id.label("metric_id"),
                LatestMetric.device_id.label("device_id"),
            )
            .where(LatestMetric.metric_name == "ping")
            .subquery()
        )

    @staticmethod
    def _search_filter(search: str | None):
        if not search:
            return None
        search_term = f"%{search.strip()}%"
        return or_(
            Device.name.ilike(search_term),
            Device.ip_address.ilike(search_term),
            Device.site.ilike(search_term),
        )

    def _device_status_query(
        self,
        *,
        active_only: bool = False,
        device_id: int | None = None,
        device_type: str | None = None,
        latest_status: str | list[str] | tuple[str, ...] | None = None,
        search: str | None = None,
    ):
        latest_ping_metrics = self._latest_ping_metrics_subquery()
        latest_ping = aliased(Metric)
        columns = [
            Device.id,
            Device.name,
            Device.ip_address,
            Device.device_type,
            Device.site,
            Device.description,
            Device.is_active,
            latest_ping.status.label("latest_status"),
            latest_ping.checked_at.label("latest_checked_at"),
        ]

        query = (
            select(*columns)
            .outerjoin(latest_ping_metrics, Device.id == latest_ping_metrics.c.device_id)
            .outerjoin(
                latest_ping,
                latest_ping.id == latest_ping_metrics.c.metric_id,
            )
        )
        if active_only:
            query = query.where(Device.is_active.is_(True))
        if device_id is not None:
            query = query.where(Device.id == device_id)
        if device_type:
            query = query.where(Device.device_type == device_type)
        if latest_status:
            normalized_status = func.coalesce(latest_ping.status, "unknown")
            if isinstance(latest_status, (list, tuple, set)):
                query = query.where(normalized_status.in_(list(latest_status)))
            else:
                query = query.where(normalized_status == latest_status)
        search_filter = self._search_filter(search)
        if search_filter is not None:
            query = query.where(search_filter)
        return query, latest_ping

    async def list_devices(self, active_only: bool = False) -> list[Device]:
        query: Select[tuple[Device]] = select(Device).order_by(Device.name.asc())
        if active_only:
            query = query.where(Device.is_active.is_(True))
        return list((await self.db.scalars(query)).all())

    async def count_devices(self, active_only: bool = False) -> int:
        query = select(func.count()).select_from(Device)
        if active_only:
            query = query.where(Device.is_active.is_(True))
        return int(await self.db.scalar(query) or 0)

    async def list_device_status_rows(
        self,
        active_only: bool = False,
        device_id: int | None = None,
        device_type: str | None = None,
        latest_status: str | list[str] | tuple[str, ...] | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        query, _latest_ping = self._device_status_query(
            active_only=active_only,
            device_id=device_id,
            device_type=device_type,
            latest_status=latest_status,
            search=search,
        )
        query = query.order_by(Device.name.asc())
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        rows = (await self.db.execute(query)).all()
        return [
            {
                "id": row.id,
                "name": row.name,
                "ip_address": row.ip_address,
                "device_type": row.device_type,
                "site": row.site,
                "description": row.description,
                "is_active": row.is_active,
                "latest_status": row.latest_status or "unknown",
                "latest_checked_at": row.latest_checked_at,
            }
            for row in rows
        ]

    async def list_device_status_rows_paged(
        self,
        *,
        active_only: bool = False,
        device_type: str | None = None,
        latest_status: str | list[str] | tuple[str, ...] | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        query, _latest_ping = self._device_status_query(
            active_only=active_only,
            device_type=device_type,
            latest_status=latest_status,
            search=search,
        )
        rows = (
            await self.db.execute(
                query.order_by(Device.name.asc()).offset(offset).limit(limit)
            )
        ).all()
        if offset == 0 and len(rows) < limit:
            total = len(rows)
        else:
            total = await self.count_device_status_rows(
                active_only=active_only,
                device_type=device_type,
                latest_status=latest_status,
                search=search,
            )
        return [
            {
                "id": row.id,
                "name": row.name,
                "ip_address": row.ip_address,
                "device_type": row.device_type,
                "site": row.site,
                "description": row.description,
                "is_active": row.is_active,
                "latest_status": row.latest_status or "unknown",
                "latest_checked_at": row.latest_checked_at,
            }
            for row in rows
        ], total

    async def summarize_active_device_statuses(self) -> dict[str, dict[str, int]]:
        latest_ping_metrics = self._latest_ping_metrics_subquery()
        latest_ping = aliased(Metric)
        latest_status = func.coalesce(latest_ping.status, "unknown").label("latest_status")
        query = (
            select(
                Device.device_type,
                latest_status,
                func.count().label("device_count"),
            )
            .outerjoin(latest_ping_metrics, Device.id == latest_ping_metrics.c.device_id)
            .outerjoin(
                latest_ping,
                latest_ping.id == latest_ping_metrics.c.metric_id,
            )
            .where(Device.is_active.is_(True))
            .group_by(Device.device_type, latest_status)
        )
        rows = (await self.db.execute(query)).all()
        summary: dict[str, dict[str, int]] = {}
        for device_type, status, device_count in rows:
            summary.setdefault(device_type, {})[str(status or "unknown")] = int(device_count)
        return summary

    async def summarize_device_status_counts(self, *, active_only: bool = False) -> dict[str, int]:
        latest_ping_metrics = self._latest_ping_metrics_subquery()
        latest_ping = aliased(Metric)
        latest_status = func.coalesce(latest_ping.status, "unknown").label("latest_status")
        query = (
            select(
                latest_status,
                func.count().label("device_count"),
            )
            .select_from(Device)
            .outerjoin(latest_ping_metrics, Device.id == latest_ping_metrics.c.device_id)
            .outerjoin(
                latest_ping,
                latest_ping.id == latest_ping_metrics.c.metric_id,
            )
        )
        if active_only:
            query = query.where(Device.is_active.is_(True))
        query = query.group_by(latest_status)
        rows = (await self.db.execute(query)).all()
        return {str(status or "unknown"): int(device_count) for status, device_count in rows}

    async def latest_device_check_at(self, *, active_only: bool = False) -> object | None:
        latest_ping_metrics = self._latest_ping_metrics_subquery()
        latest_ping = aliased(Metric)
        query = (
            select(func.max(latest_ping.checked_at))
            .select_from(Device)
            .outerjoin(latest_ping_metrics, Device.id == latest_ping_metrics.c.device_id)
            .outerjoin(latest_ping, latest_ping.id == latest_ping_metrics.c.metric_id)
        )
        if active_only:
            query = query.where(Device.is_active.is_(True))
        return await self.db.scalar(query)

    async def count_device_status_rows(
        self,
        *,
        active_only: bool = False,
        device_type: str | None = None,
        latest_status: str | list[str] | tuple[str, ...] | None = None,
        search: str | None = None,
    ) -> int:
        query, _latest_ping = self._device_status_query(
            active_only=active_only,
            device_type=device_type,
            latest_status=latest_status,
            search=search,
        )
        query = query.with_only_columns(func.count()).order_by(None)
        return int(await self.db.scalar(query) or 0)

    async def list_by_type(self, device_type: str, active_only: bool = True) -> list[Device]:
        query: Select[tuple[Device]] = select(Device).where(Device.device_type == device_type)
        if active_only:
            query = query.where(Device.is_active.is_(True))
        query = query.order_by(Device.name.asc())
        return list((await self.db.scalars(query)).all())

    async def list_by_types(self, device_types: list[str], active_only: bool = True) -> list[Device]:
        query: Select[tuple[Device]] = select(Device).where(Device.device_type.in_(device_types))
        if active_only:
            query = query.where(Device.is_active.is_(True))
        query = query.order_by(Device.name.asc())
        return list((await self.db.scalars(query)).all())

    async def get_by_id(self, device_id: int) -> Device | None:
        return await self.db.get(Device, device_id)

    async def get_by_ip_address(self, ip_address: str) -> Device | None:
        query: Select[tuple[Device]] = select(Device).where(Device.ip_address == ip_address)
        return (await self.db.scalars(query)).first()

    async def upsert_devices(self, payloads: list[dict]) -> list[Device]:
        if not payloads:
            return []

        existing = {
            device.ip_address: device
            for device in (
                await self.db.scalars(select(Device).where(Device.ip_address.in_([item["ip_address"] for item in payloads])))
            ).all()
        }

        devices: list[Device] = []
        for payload in payloads:
            device = existing.get(payload["ip_address"])
            if device is None:
                device = Device(**payload)
                self.db.add(device)
            else:
                for field, value in payload.items():
                    setattr(device, field, value)
            devices.append(device)

        await self.db.flush()
        await self.db.commit()
        return devices

    async def create_device(self, payload: dict) -> Device:
        device = Device(**payload)
        self.db.add(device)
        await self.db.flush()
        await self.db.commit()
        return device

    async def update_device(self, device: Device, payload: dict) -> Device:
        for field, value in payload.items():
            setattr(device, field, value)
        await self.db.flush()
        await self.db.commit()
        return device

    async def delete_device(self, device: Device) -> None:
        device_id = device.id
        await self.db.execute(update(Alert).where(Alert.device_id == device_id).values(device_id=None))
        await self.db.execute(update(Incident).where(Incident.device_id == device_id).values(device_id=None))
        await self.db.execute(delete(MetricDailyRollup).where(MetricDailyRollup.device_id == device_id))
        await self.db.execute(delete(MetricColdArchive).where(MetricColdArchive.device_id == device_id))
        await self.db.delete(device)
        await self.db.commit()
