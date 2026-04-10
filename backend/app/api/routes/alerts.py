from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...api.schemas import AlertItem
from ...db.session import get_db
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository

router = APIRouter()


@router.get("/active", response_model=list[AlertItem])
async def get_active_alerts(db: Session = Depends(get_db)) -> list[AlertItem]:
    devices = {device.id: device for device in DeviceRepository(db).list_devices(active_only=False)}
    alerts = AlertRepository(db).list_active_alerts()
    return [
        AlertItem(
            id=alert.id,
            device_id=alert.device_id,
            device_name=devices.get(alert.device_id).name if alert.device_id in devices else None,
            alert_type=alert.alert_type,
            severity=alert.severity,
            message=alert.message,
            status=alert.status,
            created_at=alert.created_at,
            resolved_at=alert.resolved_at,
        )
        for alert in alerts
    ]
