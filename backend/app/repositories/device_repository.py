"""Provide database query and persistence repositories for the network monitoring project."""

from sqlalchemy import Select, and_, case, delete, func, or_, select, update
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
    """Represent device repository behavior and data for database query and persistence repositories.
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
    def _latest_ping_metrics_subquery():
        """Handle the internal latest ping metrics subquery helper logic for database query and persistence repositories.

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        mikrotik_device_filter = or_(
            func.lower(Device.device_type) == "mikrotik",
            func.lower(Device.name).like("%mikrotik%"),
        )
        health_metric_priority = case(
            (LatestMetric.metric_name == "ping", 0),
            (
                and_(
                    mikrotik_device_filter,
                    LatestMetric.metric_name == "mikrotik_api",
                ),
                1,
            ),
            else_=2,
        )
        ranked_health_metrics = (
            select(
                LatestMetric.metric_id.label("metric_id"),
                LatestMetric.device_id.label("device_id"),
                func.row_number()
                .over(
                    partition_by=LatestMetric.device_id,
                    order_by=(
                        health_metric_priority.asc(),
                        LatestMetric.checked_at.desc(),
                        LatestMetric.metric_id.desc(),
                    ),
                )
                .label("rank"),
            )
            .join(Device, Device.id == LatestMetric.device_id)
            .where(
                or_(
                    LatestMetric.metric_name == "ping",
                    and_(
                        mikrotik_device_filter,
                        LatestMetric.metric_name == "mikrotik_api",
                    ),
                )
            )
            .subquery()
        )
        return (
            select(
                ranked_health_metrics.c.metric_id,
                ranked_health_metrics.c.device_id,
            )
            .where(ranked_health_metrics.c.rank == 1)
            .subquery()
        )

    @staticmethod
    def _search_filter(search: str | None):
        """Handle the internal search filter helper logic for database query and persistence repositories.

        Args:
            search: search value used by this routine (type `str | None`).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
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
        """Handle the internal device status query helper logic for database query and persistence repositories.

        Args:
            active_only: active only keyword value used by this routine (type `bool`, optional).
            device_id: device id keyword value used by this routine (type `int | None`, optional).
            device_type: device type keyword value used by this routine (type `str | None`, optional).
            latest_status: latest status keyword value used by this routine (type `str | list[str] | tuple[str, ...] | None`, optional).
            search: search keyword value used by this routine (type `str | None`, optional).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
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
            query = query.where(func.lower(Device.device_type) == str(device_type).lower())
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
        """Return a list of devices for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only value used by this routine (type `bool`, optional).

        Returns:
            `list[Device]` result produced by the routine.
        """
        query: Select[tuple[Device]] = select(Device).order_by(Device.name.asc())
        if active_only:
            query = query.where(Device.is_active.is_(True))
        return list((await self.db.scalars(query)).all())

    async def list_device_options(
        self,
        *,
        active_only: bool = False,
        search: str | None = None,
        limit: int = 300,
        offset: int = 0,
    ) -> list[dict]:
        """Return a list of device options for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only keyword value used by this routine (type `bool`, optional).
            search: search keyword value used by this routine (type `str | None`, optional).
            limit: limit keyword value used by this routine (type `int`, optional).
            offset: offset keyword value used by this routine (type `int`, optional).

        Returns:
            `list[dict]` result produced by the routine.
        """
        query = select(
            Device.id,
            Device.name,
            Device.ip_address,
            Device.device_type,
            Device.site,
            Device.is_active,
        )
        if active_only:
            query = query.where(Device.is_active.is_(True))
        search_filter = self._search_filter(search)
        if search_filter is not None:
            query = query.where(search_filter)
        rows = (
            await self.db.execute(
                query.order_by(Device.name.asc()).offset(offset).limit(limit)
            )
        ).all()
        return [
            {
                "id": row.id,
                "name": row.name,
                "ip_address": row.ip_address,
                "device_type": row.device_type,
                "site": row.site,
                "is_active": row.is_active,
            }
            for row in rows
        ]

    async def count_devices(self, active_only: bool = False) -> int:
        """Count devices for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only value used by this routine (type `bool`, optional).

        Returns:
            `int` result produced by the routine.
        """
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
        """Return a list of device status rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only value used by this routine (type `bool`, optional).
            device_id: device id value used by this routine (type `int | None`, optional).
            device_type: device type value used by this routine (type `str | None`, optional).
            latest_status: latest status value used by this routine (type `str | list[str] | tuple[str, ...] | None`, optional).
            search: search value used by this routine (type `str | None`, optional).
            limit: limit value used by this routine (type `int | None`, optional).
            offset: offset value used by this routine (type `int`, optional).

        Returns:
            `list[dict]` result produced by the routine.
        """
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
        """Return a list of device status rows paged for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only keyword value used by this routine (type `bool`, optional).
            device_type: device type keyword value used by this routine (type `str | None`, optional).
            latest_status: latest status keyword value used by this routine (type `str | list[str] | tuple[str, ...] | None`, optional).
            search: search keyword value used by this routine (type `str | None`, optional).
            limit: limit keyword value used by this routine (type `int`, optional).
            offset: offset keyword value used by this routine (type `int`, optional).

        Returns:
            `tuple[list[dict], int]` result produced by the routine.
        """
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
        """Summarize active device statuses for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `dict[str, dict[str, int]]` result produced by the routine.
        """
        latest_ping_metrics = self._latest_ping_metrics_subquery()
        latest_ping = aliased(Metric)
        latest_status = func.coalesce(latest_ping.status, "unknown").label("latest_status")
        query = (
            select(
                func.lower(Device.device_type).label("device_type"),
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
            normalized_device_type = str(device_type or "unknown").lower()
            normalized_status = str(status or "unknown")
            summary.setdefault(normalized_device_type, {})[normalized_status] = int(device_count)
        mikrotik_rows = await self._summarize_active_mikrotik_named_statuses()
        if mikrotik_rows:
            summary["mikrotik"] = mikrotik_rows
        return summary

    async def _summarize_active_mikrotik_named_statuses(self) -> dict[str, int]:
        """Summarize active mikrotik named statuses for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `dict[str, int]` result produced by the routine.
        """
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
            .where(Device.is_active.is_(True))
            .where(
                or_(
                    func.lower(Device.device_type) == "mikrotik",
                    func.lower(Device.name).like("%mikrotik%"),
                )
            )
            .group_by(latest_status)
        )
        rows = (await self.db.execute(query)).all()
        return {str(status or "unknown"): int(device_count) for status, device_count in rows}

    async def summarize_device_status_counts(self, *, active_only: bool = False) -> dict[str, int]:
        """Summarize device status counts for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only keyword value used by this routine (type `bool`, optional).

        Returns:
            `dict[str, int]` result produced by the routine.
        """
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
        """Handle latest device check at for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only keyword value used by this routine (type `bool`, optional).

        Returns:
            `object | None` result produced by the routine.
        """
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
        """Count device status rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            active_only: active only keyword value used by this routine (type `bool`, optional).
            device_type: device type keyword value used by this routine (type `str | None`, optional).
            latest_status: latest status keyword value used by this routine (type `str | list[str] | tuple[str, ...] | None`, optional).
            search: search keyword value used by this routine (type `str | None`, optional).

        Returns:
            `int` result produced by the routine.
        """
        query, _latest_ping = self._device_status_query(
            active_only=active_only,
            device_type=device_type,
            latest_status=latest_status,
            search=search,
        )
        query = query.with_only_columns(func.count()).order_by(None)
        return int(await self.db.scalar(query) or 0)

    async def list_by_type(self, device_type: str, active_only: bool = True) -> list[Device]:
        """Return a list of by type for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_type: device type value used by this routine (type `str`).
            active_only: active only value used by this routine (type `bool`, optional).

        Returns:
            `list[Device]` result produced by the routine.
        """
        query: Select[tuple[Device]] = select(Device).where(Device.device_type == device_type)
        if active_only:
            query = query.where(Device.is_active.is_(True))
        query = query.order_by(Device.name.asc())
        return list((await self.db.scalars(query)).all())

    async def list_by_types(self, device_types: list[str], active_only: bool = True) -> list[Device]:
        """Return a list of by types for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_types: device types value used by this routine (type `list[str]`).
            active_only: active only value used by this routine (type `bool`, optional).

        Returns:
            `list[Device]` result produced by the routine.
        """
        query: Select[tuple[Device]] = select(Device).where(Device.device_type.in_(device_types))
        if active_only:
            query = query.where(Device.is_active.is_(True))
        query = query.order_by(Device.name.asc())
        return list((await self.db.scalars(query)).all())

    async def get_by_id(self, device_id: int) -> Device | None:
        """Return by id for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device_id: device id value used by this routine (type `int`).

        Returns:
            `Device | None` result produced by the routine.
        """
        return await self.db.get(Device, device_id)

    async def get_by_ip_address(self, ip_address: str) -> Device | None:
        """Return by ip address for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            ip_address: ip address value used by this routine (type `str`).

        Returns:
            `Device | None` result produced by the routine.
        """
        query: Select[tuple[Device]] = select(Device).where(Device.ip_address == ip_address)
        return (await self.db.scalars(query)).first()

    async def upsert_devices(self, payloads: list[dict]) -> list[Device]:
        """Handle upsert devices for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            payloads: payloads value used by this routine (type `list[dict]`).

        Returns:
            `list[Device]` result produced by the routine.
        """
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
        """Create device for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            payload: payload value used by this routine (type `dict`).

        Returns:
            `Device` result produced by the routine.
        """
        device = Device(**payload)
        self.db.add(device)
        await self.db.flush()
        await self.db.commit()
        return device

    async def update_device(self, device: Device, payload: dict) -> Device:
        """Update device for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device: device value used by this routine (type `Device`).
            payload: payload value used by this routine (type `dict`).

        Returns:
            `Device` result produced by the routine.
        """
        for field, value in payload.items():
            setattr(device, field, value)
        await self.db.flush()
        await self.db.commit()
        return device

    async def delete_device(self, device: Device) -> None:
        """Delete device for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            device: device value used by this routine (type `Device`).

        Returns:
            None. The routine is executed for its side effects.
        """
        device_id = device.id
        await self.db.execute(update(Alert).where(Alert.device_id == device_id).values(device_id=None))
        await self.db.execute(update(Incident).where(Incident.device_id == device_id).values(device_id=None))
        await self.db.execute(delete(MetricDailyRollup).where(MetricDailyRollup.device_id == device_id))
        await self.db.execute(delete(MetricColdArchive).where(MetricColdArchive.device_id == device_id))
        await self.db.delete(device)
        await self.db.commit()
