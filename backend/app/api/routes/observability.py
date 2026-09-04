"""FastAPI routes for observability endpoints."""

from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_admin_access

from ...api.schemas import AuthObservabilitySummary
from ...db.session import check_database_connection, database_pool_health, get_db
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...repositories.threshold_repository import ThresholdRepository
from ...services.auth_service import build_auth_observability_summary
from ...core.time import utcnow
from ...models.collector_run import CollectorRun
from ...models.metric import Metric
from ...services.pipeline_control import pipeline_lock_health
from ...services.observability_service import (
    build_collector_health_rows,
    build_observability_runtime_info,
    build_scheduler_job_health_rows,
    build_scheduler_operational_alerts,
    list_scheduler_job_statuses,
    render_prometheus_metrics,
)

router = APIRouter()


@router.get("/summary", dependencies=[Depends(require_admin_access)])
async def observability_summary(db: AsyncSession = Depends(get_db)) -> dict:
    """Handle the observability summary endpoint."""
    database_ok = await check_database_connection()
    devices_total = await DeviceRepository(db).count_devices(active_only=False)
    metrics_latest_snapshot = await MetricRepository(db).count_latest_metrics()
    alerts_active = await AlertRepository(db).count_active_alerts()
    incidents_active = await IncidentRepository(db).count_active_incidents()
    thresholds_total = await ThresholdRepository(db).count_thresholds()
    auth = AuthObservabilitySummary(**await build_auth_observability_summary(db))
    scheduler_statuses = await list_scheduler_job_statuses(db)
    scheduler_alerts = build_scheduler_operational_alerts(scheduler_statuses)
    scheduler_health = build_scheduler_job_health_rows(scheduler_statuses)
    collector_health = build_collector_health_rows(
        await MetricRepository(db).summarize_collector_health(checked_from=utcnow() - timedelta(hours=24))
    )
    collector_run_rows = (
        await db.execute(
            select(
                CollectorRun.collector_name,
                func.count(CollectorRun.id).label("runs"),
                func.sum(case((CollectorRun.status == "ok", 1), else_=0)).label("successful_runs"),
                func.avg(CollectorRun.duration_ms).label("average_duration_ms"),
                func.max(CollectorRun.duration_ms).label("max_duration_ms"),
                func.sum(CollectorRun.metric_count).label("metric_writes"),
                func.max(CollectorRun.checked_at).label("last_checked_at"),
            )
            .where(CollectorRun.checked_at >= utcnow() - timedelta(hours=24))
            .group_by(CollectorRun.collector_name)
            .order_by(CollectorRun.collector_name)
        )
    ).all()
    now = utcnow()
    metric_write_rows = await db.execute(
        select(
            func.sum(case((Metric.checked_at >= now - timedelta(minutes=1), 1), else_=0)).label("last_minute"),
            func.sum(case((Metric.checked_at >= now - timedelta(hours=1), 1), else_=0)).label("last_hour"),
        ).where(Metric.checked_at >= now - timedelta(hours=1))
    )
    write_rate = metric_write_rows.one()
    scheduler_queue_risk = sum(
        1
        for row in scheduler_health
        if float(row.get("schedule_lag_seconds") or 0) > 0
    )
    scheduler_missed_windows = sum(1 for row in scheduler_health if str(row.get("state")) == "stale")
    return {
        "database": "up" if database_ok else "down",
        "devices_total": devices_total,
        "metrics_latest_snapshot": metrics_latest_snapshot,
        "alerts_active": alerts_active,
        "incidents_active": incidents_active,
        "thresholds_total": thresholds_total,
        "auth": auth.model_dump(),
        "runtime": build_observability_runtime_info(),
        "database_pool": database_pool_health(),
        "scheduler_queue": {
            "lagging_jobs": scheduler_queue_risk,
            "misfire_count": scheduler_missed_windows,
            "note": "Missed window diturunkan dari heartbeat stale; APScheduler coalescing aktif.",
        },
        "pipeline_locks": pipeline_lock_health(),
        "raw_metric_write_rate": {
            "last_minute": int(write_rate.last_minute or 0),
            "last_hour": int(write_rate.last_hour or 0),
            "per_minute_last_hour": round(float(write_rate.last_hour or 0) / 60, 2),
        },
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
        "scheduler_health": scheduler_health,
        "collector_health": collector_health,
        "collector_health_window_hours": 24,
        "collector_runs": [
            {"collector": row.collector_name, "runs": int(row.runs or 0), "successful_runs": int(row.successful_runs or 0), "average_duration_ms": float(row.average_duration_ms or 0), "max_duration_ms": float(row.max_duration_ms or 0), "metric_writes": int(row.metric_writes or 0), "last_checked_at": row.last_checked_at}
            for row in collector_run_rows
        ],
        "operational_alerts": scheduler_alerts,
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def observability_metrics(db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    """Handle the observability metrics endpoint."""
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
