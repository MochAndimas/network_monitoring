"""Database query helpers for alert repository data."""

from datetime import datetime

from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert import Alert
from ..models.device import Device


class AlertRepository:
    """Database access object for Alert records."""
    def __init__(self, db: AsyncSession):
        """Initialize the object with its runtime dependencies."""
        self.db = db

    async def list_active_alerts(self) -> list[Alert]:
        """Query active alerts from the database."""
        query: Select[tuple[Alert]] = (
            select(Alert).where(Alert.status == "active").order_by(desc(Alert.created_at), desc(Alert.id))
        )
        return list((await self.db.scalars(query)).all())

    async def list_active_alerts_by_types(self, alert_types: set[str]) -> list[Alert]:
        """Return active alerts managed by a bounded alert type set."""
        if not alert_types:
            return []
        query: Select[tuple[Alert]] = (
            select(Alert)
            .where(Alert.status == "active", Alert.alert_type.in_(alert_types))
            .order_by(desc(Alert.created_at), desc(Alert.id))
        )
        return list((await self.db.scalars(query)).all())

    async def list_active_alert_rows(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        severity: str | None = None,
        site: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        """Query active alert rows from the database."""
        query = (
            select(Alert, Device.name, Device.site)
            .outerjoin(Device, Device.id == Alert.device_id)
            .where(Alert.status == "active")
            .order_by(desc(Alert.created_at), desc(Alert.id))
        )
        normalized_severity = str(severity or "").strip().lower()
        if normalized_severity:
            query = query.where(func.lower(Alert.severity) == normalized_severity)
        normalized_site = str(site or "").strip().lower()
        if normalized_site:
            query = query.where(func.lower(Device.site) == normalized_site)
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
                "site": row_site,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "status": alert.status,
                "created_at": alert.created_at,
                "resolved_at": alert.resolved_at,
            }
            for alert, device_name, row_site in rows
        ]

    async def list_active_alert_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        severity: str | None = None,
        site: str | None = None,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        """Query active alert rows paged from the database."""
        rows = await self.list_active_alert_rows(
            limit=limit,
            offset=offset,
            severity=severity,
            site=site,
            search=search,
        )
        if offset == 0 and len(rows) < limit:
            return rows, len(rows)
        total = await self.count_active_alerts(severity=severity, site=site, search=search)
        return rows, total

    async def summarize_active_alert_severity_counts(self) -> dict[str, int]:
        """Query active alert severity counts from the database."""
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
        site: str | None = None,
        search: str | None = None,
    ) -> int:
        """Query active alerts from the database."""
        query = select(func.count()).select_from(Alert).where(Alert.status == "active")
        normalized_severity = str(severity or "").strip().lower()
        if normalized_severity:
            query = query.where(func.lower(Alert.severity) == normalized_severity)
        normalized_site = str(site or "").strip().lower()
        if normalized_site:
            query = query.join(Device, Device.id == Alert.device_id, isouter=True).where(func.lower(Device.site) == normalized_site)
        normalized_search = str(search or "").strip().lower()
        needs_device_join = bool(normalized_search) and not normalized_site
        if normalized_search:
            if needs_device_join:
                query = query.join(Device, Device.id == Alert.device_id, isouter=True)
            query = query.where(
                or_(
                    func.lower(Alert.message).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        return int(await self.db.scalar(query) or 0)

    async def create_alert(self, payload: dict, *, commit: bool = True) -> Alert:
        """Persist alert changes in the database."""
        alert = Alert(**payload)
        self.db.add(alert)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(alert)
        return alert

    async def resolve_alert(self, alert: Alert, resolved_at, *, commit: bool = True) -> Alert:
        """Persist alert changes in the database."""
        alert.status = "resolved"
        alert.resolved_at = resolved_at
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(alert)
        return alert

    async def mark_telegram_notified(self, alert: Alert, notified_at, *, commit: bool = True) -> Alert:
        """Mark that an alert active notification was sent to Telegram."""
        alert.telegram_notified_at = notified_at
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(alert)
        return alert

    async def has_recent_telegram_notified_alert(
        self,
        *,
        device_id: int | None,
        alert_type: str,
        since: datetime,
    ) -> bool:
        """Return whether a matching alert row was recently notified to Telegram."""
        query = (
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.device_id == device_id,
                Alert.alert_type == alert_type,
                Alert.telegram_notified_at.is_not(None),
                Alert.telegram_notified_at >= since,
            )
        )
        return int(await self.db.scalar(query) or 0) > 0
