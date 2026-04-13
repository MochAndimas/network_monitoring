import logging

from ..core.config import settings
from ..db.session import SessionLocal
from ..alerting.engine import evaluate_alerts
from ..monitors.device.service import run_device_checks
from ..monitors.internet.service import run_internet_checks
from ..monitors.mikrotik.service import run_mikrotik_checks
from ..monitors.server.service import run_server_checks
from ..services.pipeline_control import monitoring_pipeline_guard
from ..services.monitoring_service import persist_metrics
from ..services.retention_service import cleanup_monitoring_data


logger = logging.getLogger("network_monitoring.scheduler")


def register_jobs(scheduler) -> None:
    scheduler.add_job(
        run_internet_job,
        "interval",
        seconds=settings.scheduler_interval_internet_seconds,
        id="internet_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=settings.scheduler_job_max_instances,
        misfire_grace_time=_misfire_grace_time(settings.scheduler_interval_internet_seconds),
    )
    scheduler.add_job(
        run_device_job,
        "interval",
        seconds=settings.scheduler_interval_device_seconds,
        id="device_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=settings.scheduler_job_max_instances,
        misfire_grace_time=_misfire_grace_time(settings.scheduler_interval_device_seconds),
    )
    scheduler.add_job(
        run_server_job,
        "interval",
        seconds=settings.scheduler_interval_server_seconds,
        id="server_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=settings.scheduler_job_max_instances,
        misfire_grace_time=_misfire_grace_time(settings.scheduler_interval_server_seconds),
    )
    scheduler.add_job(
        run_mikrotik_job,
        "interval",
        seconds=settings.scheduler_interval_mikrotik_seconds,
        id="mikrotik_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=settings.scheduler_job_max_instances,
        misfire_grace_time=_misfire_grace_time(settings.scheduler_interval_mikrotik_seconds),
    )
    scheduler.add_job(
        run_alert_job,
        "interval",
        seconds=settings.scheduler_interval_alert_seconds,
        id="alert_evaluation",
        replace_existing=True,
        coalesce=True,
        max_instances=settings.scheduler_job_max_instances,
        misfire_grace_time=_misfire_grace_time(settings.scheduler_interval_alert_seconds),
    )
    scheduler.add_job(
        run_cleanup_job,
        "interval",
        hours=settings.scheduler_cleanup_interval_hours,
        id="retention_cleanup",
        replace_existing=True,
        coalesce=True,
        max_instances=settings.scheduler_job_max_instances,
        misfire_grace_time=_misfire_grace_time(settings.scheduler_cleanup_interval_hours * 3600),
    )


async def run_internet_job() -> None:
    await _persist_runner(run_internet_checks)


async def run_device_job() -> None:
    await _persist_runner(run_device_checks)


async def run_server_job() -> None:
    await _persist_runner(run_server_checks)


async def run_mikrotik_job() -> None:
    await _persist_runner(run_mikrotik_checks)


async def run_alert_job() -> None:
    async with monitoring_pipeline_guard(wait=False) as acquired:
        if not acquired:
            logger.info("Skipping alert evaluation because another monitoring pipeline run is active")
            return
        async with SessionLocal() as db:
            await evaluate_alerts(db)


async def run_cleanup_job() -> None:
    async with monitoring_pipeline_guard(wait=False) as acquired:
        if not acquired:
            logger.info("Skipping retention cleanup because another monitoring pipeline run is active")
            return
        async with SessionLocal() as db:
            await cleanup_monitoring_data(db)


async def _persist_runner(runner) -> None:
    async with monitoring_pipeline_guard(wait=False) as acquired:
        if not acquired:
            logger.info("Skipping %s because another monitoring pipeline run is active", runner.__name__)
            return
        async with SessionLocal() as db:
            await persist_metrics(db, await runner(db))


def _misfire_grace_time(period_seconds: int) -> int:
    return max(period_seconds * 2, 30)
