"""Provide database query and persistence repositories for the network monitoring project."""

from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.device import Device
from ..models.incident import Incident


class IncidentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_incidents(self) -> list[Incident]:
        query: Select[tuple[Incident]] = (
            select(Incident).where(Incident.status == "active").order_by(desc(Incident.started_at), desc(Incident.id))
        )
        return list((await self.db.scalars(query)).all())

    async def count_active_incidents(self) -> int:
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

    async def list_incident_rows_paged(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        rows = await self.list_incident_rows(status=status, limit=limit, offset=offset, search=search)
        if offset == 0 and len(rows) < limit:
            return rows, len(rows)
        return rows, await self.count_incident_rows(status=status, search=search)

    async def count_incident_rows(self, *, status: str | None = None, search: str | None = None) -> int:
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

    async def create_incident(self, payload: dict, *, commit: bool = True) -> Incident:
        incident = Incident(**payload)
        self.db.add(incident)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def resolve_incident(self, incident: Incident, ended_at, *, commit: bool = True) -> Incident:
        incident.status = "resolved"
        incident.ended_at = ended_at
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident
