"""Provide database query and persistence repositories for the network monitoring project."""

from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert import Alert
from ..models.device import Device


class AlertRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_alerts(self) -> list[Alert]:
        query: Select[tuple[Alert]] = (
            select(Alert).where(Alert.status == "active").order_by(desc(Alert.created_at), desc(Alert.id))
        )
        return list((await self.db.scalars(query)).all())

    async def list_active_alert_rows(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        severity: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        query = (
            select(Alert, Device.name)
            .outerjoin(Device, Device.id == Alert.device_id)
            .where(Alert.status == "active")
            .order_by(desc(Alert.created_at), desc(Alert.id))
        )
        normalized_severity = str(severity or "").strip().lower()
        if normalized_severity:
            query = query.where(func.lower(Alert.severity) == normalized_severity)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            query = query.where(
                or_(
                    func.lower(Alert.message).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        rows = (await self.db.execute(query)).all()
        return [
            {
                "id": alert.id,
                "device_id": alert.device_id,
                "device_name": device_name,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "status": alert.status,
                "created_at": alert.created_at,
                "resolved_at": alert.resolved_at,
            }
            for alert, device_name in rows
        ]

    async def list_active_alert_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        severity: str | None = None,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        rows = await self.list_active_alert_rows(
            limit=limit,
            offset=offset,
            severity=severity,
            search=search,
        )
        if offset == 0 and len(rows) < limit:
            return rows, len(rows)
        total = await self.count_active_alerts(severity=severity, search=search)
        return rows, total

    async def summarize_active_alert_severity_counts(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(Alert.severity, func.count())
                .where(Alert.status == "active")
                .group_by(Alert.severity)
            )
        ).all()
        return {str(severity or "unknown"): int(total) for severity, total in rows}

    async def count_active_alerts(
        self,
        *,
        severity: str | None = None,
        search: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Alert).where(Alert.status == "active")
        normalized_severity = str(severity or "").strip().lower()
        if normalized_severity:
            query = query.where(func.lower(Alert.severity) == normalized_severity)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            query = query.join(Device, Device.id == Alert.device_id, isouter=True).where(
                or_(
                    func.lower(Alert.message).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        return int(await self.db.scalar(query) or 0)

    async def create_alert(self, payload: dict, *, commit: bool = True) -> Alert:
        alert = Alert(**payload)
        self.db.add(alert)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(alert)
        return alert

    async def resolve_alert(self, alert: Alert, resolved_at, *, commit: bool = True) -> Alert:
        alert.status = "resolved"
        alert.resolved_at = resolved_at
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(alert)
        return alert
