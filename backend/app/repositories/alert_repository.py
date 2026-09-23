"""Database query helpers for alert repository data."""

from datetime import datetime

from sqlalchemy import Select, case, desc, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

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
        alert_type: str | None = None,
        device_id: int | None = None,
        search: str | None = None,
        sort: str = "newest",
    ) -> list[dict]:
        """Query active alert rows from the database."""
        query = (
            select(Alert, Device.name, Device.site, Device.location)
            .outerjoin(Device, Device.id == Alert.device_id)
            .where(Alert.status == "active")
        )
        query = query.where(
            *self._active_filters(
                severity=severity, site=site, alert_type=alert_type, device_id=device_id, search=search
            )
        )
        if sort == "severity":
            severity_priority = case(
                (func.lower(Alert.severity) == "critical", 0),
                (func.lower(Alert.severity) == "high", 1),
                (func.lower(Alert.severity) == "warning", 2),
                (func.lower(Alert.severity) == "low", 3),
                else_=4,
            )
            query = query.order_by(severity_priority, desc(Alert.created_at), desc(Alert.id))
        else:
            query = query.order_by(desc(Alert.created_at), desc(Alert.id))
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
                "location": location,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "status": alert.status,
                "created_at": alert.created_at,
                "resolved_at": alert.resolved_at,
            }
            for alert, device_name, row_site, location in rows
        ]

    async def list_active_alert_rows_paged(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        severity: str | None = None,
        site: str | None = None,
        alert_type: str | None = None,
        device_id: int | None = None,
        search: str | None = None,
        sort: str = "newest",
    ) -> tuple[list[dict], int]:
        """Query active alert rows paged from the database."""
        rows = await self.list_active_alert_rows(
            limit=limit,
            offset=offset,
            severity=severity,
            site=site,
            alert_type=alert_type,
            device_id=device_id,
            search=search,
            sort=sort,
        )
        if offset == 0 and len(rows) < limit:
            return rows, len(rows)
        total = await self.count_active_alerts(
            severity=severity, site=site, alert_type=alert_type, device_id=device_id, search=search
        )
        return rows, total

    @staticmethod
    def _active_filters(
        *,
        severity: str | None = None,
        site: str | None = None,
        alert_type: str | None = None,
        device_id: int | None = None,
        search: str | None = None,
    ) -> list[ColumnElement[bool]]:
        """Use identical filter semantics for alert rows, counts, and summaries."""
        clauses: list[ColumnElement[bool]] = [Alert.status == "active"]
        for column, value in ((Alert.severity, severity), (Device.site, site), (Alert.alert_type, alert_type)):
            normalized = str(value or "").strip().lower()
            if normalized:
                clauses.append(func.lower(column) == normalized)
        if device_id is not None:
            clauses.append(Alert.device_id == device_id)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            clauses.append(
                or_(
                    func.lower(Alert.message).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        return clauses

    async def summarize_active_alert_severity_counts(
        self,
        *,
        severity: str | None = None,
        site: str | None = None,
        alert_type: str | None = None,
        device_id: int | None = None,
        search: str | None = None,
    ) -> dict[str, int]:
        """Aggregate the complete filtered alert set in SQL, without loading messages."""
        severity_label = func.lower(func.coalesce(Alert.severity, "unknown"))
        query = select(severity_label, func.count()).select_from(Alert)
        if str(site or "").strip() or str(search or "").strip():
            query = query.outerjoin(Device, Device.id == Alert.device_id)
        query = query.where(
            *self._active_filters(
                severity=severity, site=site, alert_type=alert_type, device_id=device_id, search=search
            )
        ).group_by(severity_label)
        rows = (await self.db.execute(query)).all()
        return {str(label): int(total) for label, total in rows}

    async def count_active_alerts(
        self,
        *,
        severity: str | None = None,
        site: str | None = None,
        alert_type: str | None = None,
        device_id: int | None = None,
        search: str | None = None,
    ) -> int:
        """Count the same filtered set returned by the active alert list."""
        query = select(func.count()).select_from(Alert)
        if str(site or "").strip() or str(search or "").strip():
            query = query.outerjoin(Device, Device.id == Alert.device_id)
        query = query.where(
            *self._active_filters(
                severity=severity, site=site, alert_type=alert_type, device_id=device_id, search=search
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

    async def recent_telegram_notified_keys(
        self, keys: set[tuple[int | None, str]], *, since: datetime
    ) -> set[tuple[int | None, str]]:
        """Return recently notified logical keys across active and resolved rows."""
        if not keys:
            return set()
        query = select(Alert.device_id, Alert.alert_type).where(
            tuple_(Alert.device_id, Alert.alert_type).in_(keys),
            Alert.telegram_notified_at.is_not(None),
            Alert.telegram_notified_at >= since,
        )
        return {(device_id, str(alert_type).lower()) for device_id, alert_type in (await self.db.execute(query)).all()}

    async def count_recent_alerts_by_key(
        self,
        keys: set[tuple[int | None, str]],
        *,
        since: datetime,
    ) -> dict[tuple[int | None, str], int]:
        """Return recent alert counts keyed by device and alert type."""
        if not keys:
            return {}

        query = (
            select(Alert.device_id, Alert.alert_type, func.count())
            .where(
                tuple_(Alert.device_id, Alert.alert_type).in_(keys),
                Alert.created_at >= since,
            )
            .group_by(Alert.device_id, Alert.alert_type)
        )
        rows = (await self.db.execute(query)).all()
        return {(device_id, str(alert_type)): int(total) for device_id, alert_type, total in rows}

    async def list_recent_alerts_by_keys(
        self,
        keys: set[tuple[int | None, str]],
        *,
        since: datetime,
    ) -> dict[int | None, list[Alert]]:
        """Return recent alert rows grouped by device for a bounded key set."""
        if not keys:
            return {}

        query = (
            select(Alert)
            .where(
                tuple_(Alert.device_id, Alert.alert_type).in_(keys),
                Alert.created_at >= since,
            )
            .order_by(Alert.created_at.asc(), Alert.id.asc())
        )
        alerts = list((await self.db.scalars(query)).all())
        grouped: dict[int | None, list[Alert]] = {}
        for alert in alerts:
            grouped.setdefault(alert.device_id, []).append(alert)
        return grouped
