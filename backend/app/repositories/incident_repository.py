from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from ..models.incident import Incident


class IncidentRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_incidents(self, status: str | None = None, limit: int = 100) -> list[Incident]:
        query: Select[tuple[Incident]] = select(Incident)
        if status:
            query = query.where(Incident.status == status)
        query = query.order_by(desc(Incident.started_at), desc(Incident.id)).limit(limit)
        return list(self.db.scalars(query).all())

    def get_active_incident_by_device(self, device_id: int | None) -> Incident | None:
        query: Select[tuple[Incident]] = select(Incident).where(
            Incident.device_id == device_id,
            Incident.status == "active",
        )
        return self.db.scalars(query).first()

    def create_incident(self, payload: dict) -> Incident:
        incident = Incident(**payload)
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        return incident

    def resolve_incident(self, incident: Incident, ended_at) -> Incident:
        incident.status = "resolved"
        incident.ended_at = ended_at
        self.db.commit()
        self.db.refresh(incident)
        return incident
