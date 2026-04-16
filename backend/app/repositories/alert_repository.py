from sqlalchemy import Select, desc, func, select
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

    async def list_active_alert_rows(self) -> list[dict]:
        query = (
            select(Alert, Device.name)
            .outerjoin(Device, Device.id == Alert.device_id)
            .where(Alert.status == "active")
            .order_by(desc(Alert.created_at), desc(Alert.id))
        )
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

    async def count_active_alerts(self) -> int:
        query = select(func.count()).select_from(Alert).where(Alert.status == "active")
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
