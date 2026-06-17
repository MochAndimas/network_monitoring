"""scheduler support code for jobs."""

import logging
from time import perf_counter

from ..core.config import settings
from ..db.session import SessionLocal
from ..alerting.engine import evaluate_alerts
from ..monitors.device.service import run_device_checks
from ..monitors.internet.service import run_internet_checks
from ..monitors.mikrotik.service import run_mikrotik_checks
from ..monitors.server.service import run_server_checks
from ..services.auth_service import cleanup_auth_data
from ..services.observability_service import (
    job_logging_context,
    mark_scheduler_job_failed,
    mark_scheduler_job_started,
    mark_scheduler_job_succeeded,
)
from ..services.pipeline_control import monitoring_pipeline_guard
from ..services.monitoring_service import persist_metrics
from ..services.retention_service import cleanup_monitoring_data


logger = logging.getLogger("network_monitoring.scheduler")


def register_jobs(scheduler) -> None:
    """Register jobs for scheduled monitoring execution."""
    scheduler_settings = settings.scheduler
    scheduler.add_job(
        run_internet_job,
        "interval",
        seconds=scheduler_settings.interval_internet_seconds,
        id="internet_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=scheduler_settings.job_max_instances,
        misfire_grace_time=_misfire_grace_time(scheduler_settings.interval_internet_seconds),
    )
    scheduler.add_job(
        run_device_job,
        "interval",
        seconds=scheduler_settings.interval_device_seconds,
        id="device_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=scheduler_settings.job_max_instances,
        misfire_grace_time=_misfire_grace_time(scheduler_settings.interval_device_seconds),
    )
    scheduler.add_job(
        run_server_job,
        "interval",
        seconds=scheduler_settings.interval_server_seconds,
        id="server_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=scheduler_settings.job_max_instances,
        misfire_grace_time=_misfire_grace_time(scheduler_settings.interval_server_seconds),
    )
    scheduler.add_job(
        run_mikrotik_job,
        "interval",
        seconds=scheduler_settings.interval_mikrotik_seconds,
        id="mikrotik_checks",
        replace_existing=True,
        coalesce=True,
        max_instances=scheduler_settings.job_max_instances,
        misfire_grace_time=_misfire_grace_time(scheduler_settings.interval_mikrotik_seconds),
    )
    scheduler.add_job(
        run_alert_job,
        "interval",
        seconds=scheduler_settings.interval_alert_seconds,
        id="alert_evaluation",
        replace_existing=True,
        coalesce=True,
        max_instances=scheduler_settings.job_max_instances,
        misfire_grace_time=_misfire_grace_time(scheduler_settings.interval_alert_seconds),
    )
    scheduler.add_job(
        run_cleanup_job,
        "interval",
        hours=scheduler_settings.cleanup_interval_hours,
        id="retention_cleanup",
        replace_existing=True,
        coalesce=True,
        max_instances=scheduler_settings.job_max_instances,
        misfire_grace_time=_misfire_grace_time(scheduler_settings.cleanup_interval_hours * 3600),
    )


async def run_internet_job() -> None:
    """Run internet job for scheduled monitoring execution."""
    await _run_scheduler_job("internet_checks", lambda db: _persist_runner(run_internet_checks, db, lock_scope="internet"))


async def run_device_job() -> None:
    """Run device job for scheduled monitoring execution."""
    await _run_scheduler_job("device_checks", lambda db: _persist_runner(run_device_checks, db, lock_scope="device"))


async def run_server_job() -> None:
    """Run server job for scheduled monitoring execution."""
    await _run_scheduler_job("server_checks", lambda db: _persist_runner(run_server_checks, db, lock_scope="server"))


async def run_mikrotik_job() -> None:
    """Run mikrotik job for scheduled monitoring execution."""
    await _run_scheduler_job("mikrotik_checks", lambda db: _persist_runner(run_mikrotik_checks, db, lock_scope="mikrotik"))


async def run_alert_job() -> None:
    """Run alert job for scheduled monitoring execution."""
    await _run_scheduler_job("alert_evaluation", _run_alert_job_inner)


async def run_cleanup_job() -> None:
    """Run cleanup job for scheduled monitoring execution."""
    await _run_scheduler_job("retention_cleanup", _run_cleanup_job_inner)


async def _persist_runner(runner, db, *, lock_scope: str) -> None:
    # Collectors can perform slow network work without holding a pipeline lock.
    # Only metric writes are scoped by domain, while alert/incident mutation
    # remains serialized below.
    """Persist runner for scheduled monitoring execution."""
    metrics = await runner(db)
    async with monitoring_pipeline_guard(wait=True, scope=f"metrics:{lock_scope}"):
        await persist_metrics(db, metrics, commit=False)
        await db.commit()
    # Re-evaluate alerts immediately after fresh metrics land so alerting
    # doesn't get starved by the separate scheduler tick. Alert/incident state
    # is global, so this section intentionally keeps a shared lock.
    async with monitoring_pipeline_guard(wait=True, scope="alerts"):
        await evaluate_alerts(db, commit=False)
        await db.commit()


async def _run_alert_job_inner(db) -> None:
    """Run alert job inner for scheduled monitoring execution."""
    async with monitoring_pipeline_guard(wait=False, scope="alerts") as acquired:
        if not acquired:
            logger.info("Skipping alert evaluation because another monitoring pipeline run is active")
            return
        await evaluate_alerts(db, commit=False)
        await db.commit()


async def _run_cleanup_job_inner(db) -> None:
    """Run cleanup job inner for scheduled monitoring execution."""
    async with monitoring_pipeline_guard(wait=False, scope="cleanup") as acquired:
        if not acquired:
            logger.info("Skipping retention cleanup because another cleanup run is active")
            return
        await cleanup_monitoring_data(db, commit=False)
        await cleanup_auth_data(db, commit=False)
        await db.commit()


async def _run_scheduler_job(job_name: str, operation) -> None:
    """Run scheduler job for scheduled monitoring execution."""
    started_at = perf_counter()
    async with SessionLocal() as db:
        with job_logging_context(job_name):
            await mark_scheduler_job_started(db, job_name=job_name)
            try:
                await operation(db)
            except Exception as exc:
                await db.rollback()
                duration_ms = (perf_counter() - started_at) * 1000
                await mark_scheduler_job_failed(db, job_name=job_name, duration_ms=duration_ms, error=str(exc))
                logger.exception("scheduler_job_failed job_name=%s duration_ms=%.2f", job_name, duration_ms)
                raise
            else:
                duration_ms = (perf_counter() - started_at) * 1000
                await mark_scheduler_job_succeeded(db, job_name=job_name, duration_ms=duration_ms)
                logger.info("scheduler_job_completed job_name=%s duration_ms=%.2f", job_name, duration_ms)


def _misfire_grace_time(period_seconds: int) -> int:
    """Return misfire grace time for scheduled monitoring execution."""
    return max(period_seconds * 2, 30)
