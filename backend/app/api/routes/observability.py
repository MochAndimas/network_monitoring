from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from ...db.session import check_database_connection, get_db
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...repositories.threshold_repository import ThresholdRepository

router = APIRouter()


@router.get("/summary")
async def observability_summary(db: Session = Depends(get_db)) -> dict:
    return {
        "database": "up" if check_database_connection() else "down",
        "devices_total": len(DeviceRepository(db).list_devices(active_only=False)),
        "metrics_latest_snapshot": len(MetricRepository(db).latest_metric_map()),
        "alerts_active": AlertRepository(db).count_active_alerts(),
        "incidents_active": len(IncidentRepository(db).list_incidents(status="active", limit=500)),
        "thresholds_total": len(ThresholdRepository(db).list_thresholds()),
    }
