"""Provide database query and persistence repositories for the network monitoring project."""

from sqlalchemy import Select, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert import Alert
from ..models.device import Device


class AlertRepository:
    """Represent alert repository behavior and data for database query and persistence repositories.
    """
    def __init__(self, db: AsyncSession):
        """Handle the internal init helper logic for database query and persistence repositories.

        Args:
            db: db value used by this routine (type `AsyncSession`).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        self.db = db

    async def list_active_alerts(self) -> list[Alert]:
        """Return a list of active alerts for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `list[Alert]` result produced by the routine.
        """
        query: Select[tuple[Alert]] = (
            select(Alert).where(Alert.status == "active").order_by(desc(Alert.created_at), desc(Alert.id))
        )
        return list((await self.db.scalars(query)).all())

    async def list_active_alert_rows(self, *, limit: int | None = None) -> list[dict]:
        """Return a list of active alert rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            limit: limit keyword value used by this routine (type `int | None`, optional).

        Returns:
            `list[dict]` result produced by the routine.
        """
        query = (
            select(Alert, Device.name)
            .outerjoin(Device, Device.id == Alert.device_id)
            .where(Alert.status == "active")
            .order_by(desc(Alert.created_at), desc(Alert.id))
        )
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

    async def summarize_active_alert_severity_counts(self) -> dict[str, int]:
        """Summarize active alert severity counts for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `dict[str, int]` result produced by the routine.
        """
        rows = (
            await self.db.execute(
                select(Alert.severity, func.count())
                .where(Alert.status == "active")
                .group_by(Alert.severity)
            )
        ).all()
        return {str(severity or "unknown"): int(total) for severity, total in rows}

    async def count_active_alerts(self) -> int:
        """Count active alerts for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `int` result produced by the routine.
        """
        query = select(func.count()).select_from(Alert).where(Alert.status == "active")
        return int(await self.db.scalar(query) or 0)

    async def create_alert(self, payload: dict, *, commit: bool = True) -> Alert:
        """Create alert for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            payload: payload value used by this routine (type `dict`).
            commit: commit keyword value used by this routine (type `bool`, optional).

        Returns:
            `Alert` result produced by the routine.
        """
        alert = Alert(**payload)
        self.db.add(alert)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(alert)
        return alert

    async def resolve_alert(self, alert: Alert, resolved_at, *, commit: bool = True) -> Alert:
        """Resolve alert for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            alert: alert value used by this routine (type `Alert`).
            resolved_at: resolved at value used by this routine.
            commit: commit keyword value used by this routine (type `bool`, optional).

        Returns:
            `Alert` result produced by the routine.
        """
        alert.status = "resolved"
        alert.resolved_at = resolved_at
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(alert)
        return alert
