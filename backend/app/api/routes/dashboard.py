"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import DashboardSummary
from ...db.session import get_db
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...services.monitoring_service import build_dashboard_summary

router = APIRouter()


async def _build_overview_panels(
    db: AsyncSession,
    *,
    snapshot_limit: int,
    alerts_limit: int,
    incidents_limit: int,
) -> dict:
    device_repository = DeviceRepository(db)
    metric_repository = MetricRepository(db)
    summary = await build_dashboard_summary(db)
    latest_snapshot_rows, latest_snapshot_total = await metric_repository.list_latest_metric_rows_paged(
        limit=snapshot_limit,
        offset=0,
    )
    device_status_summary = await device_repository.summarize_device_status_counts(active_only=True)
    total_devices = await device_repository.count_devices(active_only=False)
    active_devices = await device_repository.count_devices(active_only=True)
    return {
        "summary": summary,
        "device_counts": {
            "total": total_devices,
            "active": active_devices,
            "inactive": max(total_devices - active_devices, 0),
            "statuses": device_status_summary,
            "latest_check_at": await device_repository.latest_device_check_at(active_only=True),
        },
        "alert_severity_summary": await AlertRepository(db).summarize_active_alert_severity_counts(),
        "alerts": await AlertRepository(db).list_active_alert_rows(limit=alerts_limit),
        "incidents": await IncidentRepository(db).list_incident_rows(status="active", limit=incidents_limit),
        "latest_snapshot": {
            "items": _metric_history_items(latest_snapshot_rows),
            "meta": {"total": latest_snapshot_total, "limit": snapshot_limit, "offset": 0},
        },
    }


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    return DashboardSummary(**await build_dashboard_summary(db))


@router.get("/overview-panels")
async def get_overview_panels(
    snapshot_limit: int = Query(default=12, ge=1, le=100),
    alerts_limit: int = Query(default=5, ge=1, le=50),
    incidents_limit: int = Query(default=5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _build_overview_panels(
        db,
        snapshot_limit=snapshot_limit,
        alerts_limit=alerts_limit,
        incidents_limit=incidents_limit,
    )


@router.get("/problem-devices")
async def get_problem_devices(
    limit: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await DeviceRepository(db).list_device_status_rows(
        active_only=True,
        latest_status=["down", "warning", "error"],
        limit=limit,
        offset=0,
    )


@router.get("/overview-data")
async def get_overview_data(db: AsyncSession = Depends(get_db)) -> dict:
    payload = await _build_overview_panels(db, snapshot_limit=12, alerts_limit=5, incidents_limit=5)
    payload["problem_devices"] = await get_problem_devices(limit=25, db=db)
    return payload


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
