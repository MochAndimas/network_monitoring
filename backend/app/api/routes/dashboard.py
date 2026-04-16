from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import DashboardSummary
from ...db.session import get_db
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...services.monitoring_service import build_dashboard_summary

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    return DashboardSummary(**await build_dashboard_summary(db))


@router.get("/overview-data")
async def get_overview_data(db: AsyncSession = Depends(get_db)) -> dict:
    device_repository = DeviceRepository(db)
    metric_repository = MetricRepository(db)
    summary = await build_dashboard_summary(db)
    latest_snapshot_rows, latest_snapshot_total = await metric_repository.list_latest_metric_rows_paged(limit=100, offset=0)
    return {
        "summary": summary,
        "devices": await device_repository.list_device_status_rows(),
        "alerts": await AlertRepository(db).list_active_alert_rows(),
        "incidents": await IncidentRepository(db).list_incident_rows(status="active"),
        "latest_snapshot": {
            "items": _metric_history_items(latest_snapshot_rows),
            "meta": {"total": latest_snapshot_total, "limit": 100, "offset": 0},
        },
    }


def _metric_history_items(rows: list[dict]) -> list[dict]:
    return [
        {
            "id": metric["id"],
            "device_id": metric["device_id"],
            "device_name": metric["device_name"],
            "metric_name": metric["metric_name"],
            "metric_value": metric["metric_value"],
            "metric_value_numeric": metric["metric_value_numeric"],
            "status": metric["status"],
            "unit": metric["unit"],
            "checked_at": metric["checked_at"],
        }
        for metric in rows
    ]
