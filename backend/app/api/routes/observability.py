"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import AuthObservabilitySummary
from ...db.session import check_database_connection, get_db
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...repositories.threshold_repository import ThresholdRepository
from ...services.auth_service import build_auth_observability_summary
from ...services.observability_service import (
    build_scheduler_operational_alerts,
    list_scheduler_job_statuses,
    render_prometheus_metrics,
)

router = APIRouter()


@router.get("/summary")
async def observability_summary(db: AsyncSession = Depends(get_db)) -> dict:
    """Handle observability summary for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `dict` result produced by the routine.
    """
    database_ok = await check_database_connection()
    devices_total = await DeviceRepository(db).count_devices(active_only=False)
    metrics_latest_snapshot = await MetricRepository(db).count_latest_metrics()
    alerts_active = await AlertRepository(db).count_active_alerts()
    incidents_active = await IncidentRepository(db).count_active_incidents()
    thresholds_total = await ThresholdRepository(db).count_thresholds()
    auth = AuthObservabilitySummary(**await build_auth_observability_summary(db))
    scheduler_statuses = await list_scheduler_job_statuses(db)
    scheduler_alerts = build_scheduler_operational_alerts(scheduler_statuses)
    return {
        "database": "up" if database_ok else "down",
        "devices_total": devices_total,
        "metrics_latest_snapshot": metrics_latest_snapshot,
        "alerts_active": alerts_active,
        "incidents_active": incidents_active,
        "thresholds_total": thresholds_total,
        "auth": auth.model_dump(),
        "scheduler_jobs": [
            {
                "job_name": job.job_name,
                "is_running": job.is_running,
                "consecutive_failures": job.consecutive_failures,
                "last_started_at": job.last_started_at,
                "last_succeeded_at": job.last_succeeded_at,
                "last_failed_at": job.last_failed_at,
                "last_duration_ms": job.last_duration_ms,
            }
            for job in scheduler_statuses
        ],
        "operational_alerts": scheduler_alerts,
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def observability_metrics(db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    """Handle observability metrics for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `PlainTextResponse` result produced by the routine.
    """
    database_ok = await check_database_connection()
    scheduler_statuses = await list_scheduler_job_statuses(db)
    scheduler_alerts = build_scheduler_operational_alerts(scheduler_statuses)
    return PlainTextResponse(
        render_prometheus_metrics(
            database_up=database_ok,
            scheduler_alert_count=len(scheduler_alerts),
            scheduler_statuses=scheduler_statuses,
        ),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
