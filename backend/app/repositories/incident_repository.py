"""Provide database query and persistence repositories for the network monitoring project."""

from sqlalchemy import Select, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.device import Device
from ..models.incident import Incident


class IncidentRepository:
    """Represent incident repository behavior and data for database query and persistence repositories.
    """
    def __init__(self, db: AsyncSession):
        """Handle the internal init helper logic for database query and persistence repositories.

        Args:
            db: db value used by this routine (type `AsyncSession`).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        self.db = db

    async def list_active_incidents(self) -> list[Incident]:
        """Return a list of active incidents for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `list[Incident]` result produced by the routine.
        """
        query: Select[tuple[Incident]] = (
            select(Incident).where(Incident.status == "active").order_by(desc(Incident.started_at), desc(Incident.id))
        )
        return list((await self.db.scalars(query)).all())

    async def count_active_incidents(self) -> int:
        """Count active incidents for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `int` result produced by the routine.
        """
        query = select(func.count()).select_from(Incident).where(Incident.status == "active")
        return int(await self.db.scalar(query) or 0)

    async def list_incident_rows(self, status: str | None = None, limit: int = 100) -> list[dict]:
        """Return a list of incident rows for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            status: status value used by this routine (type `str | None`, optional).
            limit: limit value used by this routine (type `int`, optional).

        Returns:
            `list[dict]` result produced by the routine.
        """
        query = select(Incident, Device.name).outerjoin(Device, Device.id == Incident.device_id)
        if status:
            query = query.where(Incident.status == status)
        query = query.order_by(desc(Incident.started_at), desc(Incident.id)).limit(limit)
        rows = (await self.db.execute(query)).all()
        return [
            {
                "id": incident.id,
                "device_id": incident.device_id,
                "device_name": device_name,
                "status": incident.status,
                "summary": incident.summary,
                "started_at": incident.started_at,
                "ended_at": incident.ended_at,
            }
            for incident, device_name in rows
        ]

    async def create_incident(self, payload: dict, *, commit: bool = True) -> Incident:
        """Create incident for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            payload: payload value used by this routine (type `dict`).
            commit: commit keyword value used by this routine (type `bool`, optional).

        Returns:
            `Incident` result produced by the routine.
        """
        incident = Incident(**payload)
        self.db.add(incident)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def resolve_incident(self, incident: Incident, ended_at, *, commit: bool = True) -> Incident:
        """Resolve incident for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            incident: incident value used by this routine (type `Incident`).
            ended_at: ended at value used by this routine.
            commit: commit keyword value used by this routine (type `bool`, optional).

        Returns:
            `Incident` result produced by the routine.
        """
        incident.status = "resolved"
        incident.ended_at = ended_at
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident
