from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import check_database_connection, get_db
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...repositories.threshold_repository import ThresholdRepository

router = APIRouter()


@router.get("/summary")
async def observability_summary(db: AsyncSession = Depends(get_db)) -> dict:
    database_ok = await check_database_connection()
    devices_total = await DeviceRepository(db).count_devices(active_only=False)
    metrics_latest_snapshot = await MetricRepository(db).count_latest_metrics()
    alerts_active = await AlertRepository(db).count_active_alerts()
    incidents_active = await IncidentRepository(db).count_active_incidents()
    thresholds_total = await ThresholdRepository(db).count_thresholds()
    return {
        "database": "up" if database_ok else "down",
        "devices_total": devices_total,
        "metrics_latest_snapshot": metrics_latest_snapshot,
        "alerts_active": alerts_active,
        "incidents_active": incidents_active,
        "thresholds_total": thresholds_total,
    }
