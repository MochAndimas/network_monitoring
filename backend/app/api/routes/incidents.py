from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...api.schemas import IncidentItem
from ...db.session import get_db
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository

router = APIRouter()


@router.get("", response_model=list[IncidentItem])
async def list_incidents(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[IncidentItem]:
    devices = {device.id: device for device in DeviceRepository(db).list_devices(active_only=False)}
    incidents = IncidentRepository(db).list_incidents(status=status, limit=limit)
    return [
        IncidentItem(
            id=incident.id,
            device_id=incident.device_id,
            device_name=devices.get(incident.device_id).name if incident.device_id in devices else None,
            status=incident.status,
            summary=incident.summary,
            started_at=incident.started_at,
            ended_at=incident.ended_at,
        )
        for incident in incidents
    ]
