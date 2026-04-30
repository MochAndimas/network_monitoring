"""Define module logic for `backend/app/repositories/incident_repository.py`.

This module contains project-specific implementation details.
"""

from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.time import utcnow
from ..models.alert import Alert
from ..models.device import Device
from ..models.incident import Incident


class IncidentRepository:
    """Perform IncidentRepository.

    This class encapsulates related behavior and data for this domain area.
    """
    def __init__(self, db: AsyncSession):
        """Perform init.

        Args:
            db: Parameter input untuk routine ini.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        self.db = db

    async def list_active_incidents(self) -> list[Incident]:
        """Repository method to list active incidents.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        query: Select[tuple[Incident]] = (
            select(Incident).where(Incident.status == "active").order_by(desc(Incident.started_at), desc(Incident.id))
        )
        return list((await self.db.scalars(query)).all())

    async def count_active_incidents(self) -> int:
        """Repository method to count active incidents.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        query = select(func.count()).select_from(Incident).where(Incident.status == "active")
        return int(await self.db.scalar(query) or 0)

    async def list_incident_rows(
        self,
        status: str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
    ) -> list[dict]:
        """Repository method to list incident rows.

        Args:
            status: Parameter input untuk routine ini.
            limit: Parameter input untuk routine ini.
            offset: Parameter input untuk routine ini.
            search: Parameter input untuk routine ini.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        query = select(Incident, Device.name).outerjoin(Device, Device.id == Incident.device_id)
        if status:
            query = query.where(Incident.status == status)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            query = query.where(
                or_(
                    func.lower(Incident.summary).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        query = query.order_by(desc(Incident.started_at), desc(Incident.id))
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        rows = (await self.db.execute(query)).all()
        incident_summaries = await self._incident_alert_summaries([incident for incident, _device_name in rows])
        return [
            {
                "id": incident.id,
                "device_id": incident.device_id,
                "device_name": device_name,
                "status": incident.status,
                "summary": incident_summaries.get(incident.id, incident.summary),
                "started_at": incident.started_at,
                "ended_at": incident.ended_at,
            }
            for incident, device_name in rows
        ]

    async def list_incident_rows_paged(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        """Repository method to list incident rows paged.

        Args:
            status: Parameter input untuk routine ini.
            limit: Parameter input untuk routine ini.
            offset: Parameter input untuk routine ini.
            search: Parameter input untuk routine ini.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        rows = await self.list_incident_rows(status=status, limit=limit, offset=offset, search=search)
        if offset == 0 and len(rows) < limit:
            return rows, len(rows)
        return rows, await self.count_incident_rows(status=status, search=search)

    async def count_incident_rows(self, *, status: str | None = None, search: str | None = None) -> int:
        """Repository method to count incident rows.

        Args:
            status: Parameter input untuk routine ini.
            search: Parameter input untuk routine ini.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        query = select(func.count()).select_from(Incident)
        if status:
            query = query.where(Incident.status == status)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            query = query.join(Device, Device.id == Incident.device_id, isouter=True).where(
                or_(
                    func.lower(Incident.summary).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        return int(await self.db.scalar(query) or 0)

    async def _incident_alert_summaries(self, incidents: list[Incident]) -> dict[int, str]:
        """Build richer incident summaries from alerts inside each incident window."""
        incident_windows = [
            incident
            for incident in incidents
            if incident.id is not None and incident.device_id is not None and incident.started_at is not None
        ]
        if not incident_windows:
            return {}

        now = utcnow()
        device_ids = {incident.device_id for incident in incident_windows if incident.device_id is not None}
        min_started_at = min(incident.started_at for incident in incident_windows)
        max_ended_at = max((incident.ended_at or now) for incident in incident_windows)
        alert_rows = list(
            (
                await self.db.scalars(
                    select(Alert)
                    .where(Alert.device_id.in_(device_ids))
                    .where(Alert.created_at >= min_started_at)
                    .where(Alert.created_at <= max_ended_at)
                    .order_by(Alert.created_at.asc(), Alert.id.asc())
                )
            ).all()
        )

        summaries: dict[int, str] = {}
        for incident in incident_windows:
            incident_ended_at = incident.ended_at or now
            incident_alerts = [
                alert
                for alert in alert_rows
                if alert.device_id == incident.device_id
                and alert.created_at >= incident.started_at
                and alert.created_at <= incident_ended_at
            ]
            if incident_alerts:
                summaries[incident.id] = _format_incident_alert_summary(incident_alerts)
        return summaries

    async def create_incident(self, payload: dict, *, commit: bool = True) -> Incident:
        """Repository method to create incident.

        Args:
            payload: Parameter input untuk routine ini.
            commit: Parameter input untuk routine ini.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        incident = Incident(**payload)
        self.db.add(incident)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def resolve_incident(self, incident: Incident, ended_at, *, commit: bool = True) -> Incident:
        """Repository method to return resolve incident.

        Args:
            incident: Parameter input untuk routine ini.
            ended_at: Parameter input untuk routine ini.
            commit: Parameter input untuk routine ini.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

        """
        incident.status = "resolved"
        incident.ended_at = ended_at
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident


def _format_incident_alert_summary(alerts: list[Alert]) -> str:
    """Format alert rows into a concise incident summary."""
    latest_alert_by_type: dict[str, Alert] = {}
    for alert in alerts:
        latest_alert_by_type[alert.alert_type] = alert

    ordered_alerts = sorted(latest_alert_by_type.values(), key=lambda item: (item.created_at, item.alert_type))
    alert_parts = [f"{alert.alert_type}: {alert.message}" for alert in ordered_alerts[:5]]
    extra_count = max(len(ordered_alerts) - len(alert_parts), 0)
    suffix = f"; +{extra_count} alert lain" if extra_count else ""
    return f"{len(ordered_alerts)} alert: " + "; ".join(alert_parts) + suffix
