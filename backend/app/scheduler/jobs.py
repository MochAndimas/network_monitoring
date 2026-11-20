"""scheduler support code for jobs."""

import logging
from asyncio import sleep
from collections import defaultdict
from contextlib import AsyncExitStack, asynccontextmanager
from time import perf_counter

from sqlalchemy.exc import OperationalError

from ..core.config import settings
from ..core.phase_timing import timed_phase
from ..db.session import SessionLocal
from ..services.operational_alert_service import evaluate_operational_alerts as evaluate_alerts
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
from ..services.collector_ownership import device_collector_ownership
from ..services.monitoring_service import persist_metrics
from ..services.retention_service import cleanup_monitoring_data
from ..models.collector_run import CollectorRun
from ..core.time import utcnow


logger = logging.getLogger("network_monitoring.scheduler")


def register_jobs(scheduler) -> None:
    """Register jobs for scheduled monitoring execution."""
    scheduler_settings = settings.scheduler
    # A site agent deliberately owns only its local device polling. Central
    # services keep internet/API/alert/retention work, avoiding duplicated
    # global checks and keeping management traffic inside each VPN/LAN.
    if str(settings.monitor.collector_agent_site or "").strip():
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
        return
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
    await _run_scheduler_job(
        "internet_checks", lambda db: _persist_runner(run_internet_checks, db, lock_scope="internet")
    )


async def run_device_job() -> None:
    """Run device job for scheduled monitoring execution."""
    ownership = device_collector_ownership()
    await _run_scheduler_job(
        "device_checks",
        lambda db: _persist_runner(
            lambda session: run_device_checks(
                session, site=ownership.site, excluded_sites=set(ownership.excluded_sites)
            ),
            db,
            lock_scope=ownership.lock_scope,
            commit_per_device=True,
        ),
    )


async def run_server_job() -> None:
    """Run server job for scheduled monitoring execution."""
    await _run_scheduler_job("server_checks", lambda db: _persist_runner(run_server_checks, db, lock_scope="server"))


async def run_mikrotik_job() -> None:
    """Run mikrotik job for scheduled monitoring execution."""
    await _run_scheduler_job(
        "mikrotik_checks", lambda db: _persist_runner(run_mikrotik_checks, db, lock_scope="mikrotik")
    )


async def run_alert_job() -> None:
    """Run alert job for scheduled monitoring execution."""
    await _run_scheduler_job("alert_evaluation", _run_alert_job_inner)


async def run_cleanup_job() -> None:
    """Run cleanup job for scheduled monitoring execution."""
    await _run_scheduler_job("retention_cleanup", _run_cleanup_job_inner)


@asynccontextmanager
async def _timed_guard(*, wait: bool, scope: str):
    async with AsyncExitStack() as stack:
        with timed_phase(logger, "lock_acquire", scope):
            acquired = await stack.enter_async_context(monitoring_pipeline_guard(wait=wait, scope=scope))
        if not acquired:
            logger.info("scheduler_lock_skipped scope=%s", scope)
        yield acquired


async def _persist_runner(runner, db, *, lock_scope: str, commit_per_device: bool = False) -> None:
    """Collect and commit metrics for the central periodic alert evaluator."""
    started_at = perf_counter()
    with timed_phase(logger, "collect", lock_scope):
        metrics = await runner(db)
    async with _timed_guard(wait=True, scope=f"metrics:{lock_scope}"):
        failed_devices = 0
        committed_metrics = len(metrics)
        if commit_per_device:
            committed_metrics, failed_devices = await _persist_device_batches(db, metrics, lock_scope)
        else:
            await _write_metric_batch(db, metrics, lock_scope)
        db.add(
            CollectorRun(
                collector_name=f"{lock_scope}_checks",
                status=("partial" if committed_metrics else "failed") if failed_devices else "ok",
                duration_ms=(perf_counter() - started_at) * 1000,
                metric_count=committed_metrics,
                checked_at=utcnow(),
            )
        )
        with timed_phase(logger, "commit_collector_run" if commit_per_device else "commit_metrics", lock_scope):
            await db.commit()
        if failed_devices:
            raise RuntimeError(
                f"{lock_scope}: {failed_devices} device metric batches exhausted lock retry "
                f"({committed_metrics}/{len(metrics)} metrics committed)"
            )


async def _persist_device_batches(db, metrics, scope: str) -> tuple[int, int]:
    batches = defaultdict(list)
    for metric in metrics:
        batches[int(metric["device_id"])].append(metric)

    committed = failed = 0
    for device_id, batch in sorted(batches.items()):
        device_scope = f"{scope}:device_id={device_id}"
        try:
            await _write_metric_batch(db, batch, device_scope, commit=True)
        except OperationalError as exc:
            error_code = _retryable_lock_error(exc)
            if error_code is None:
                raise
            await db.rollback()
            failed += 1
            logger.warning("metric_device_batch_failed scope=%s mysql_error_code=%s", device_scope, error_code)
        else:
            committed += len(batch)
    return committed, failed


async def _write_metric_batch(db, metrics, scope: str, *, commit: bool = False) -> None:
    for attempt in range(2):
        try:
            with timed_phase(logger, "persist_metrics", scope):
                await persist_metrics(db, metrics, commit=False)
            if commit:
                with timed_phase(logger, "commit_metrics", scope):
                    await db.commit()
            return
        except OperationalError as exc:
            error_code = _retryable_lock_error(exc)
            if attempt or error_code is None:
                raise
            await db.rollback()
            logger.warning("metric_write_retry scope=%s mysql_error_code=%s", scope, error_code)
            await sleep(0.25)


def _retryable_lock_error(exc: OperationalError) -> int | None:
    code = exc.orig.args[0] if exc.orig.args else None
    return code if not exc.connection_invalidated and code in (1205, 1213) else None


async def _run_alert_job_inner(db) -> None:
    """Run alert job inner for scheduled monitoring execution."""
    async with _timed_guard(wait=False, scope="alerts") as acquired:
        if not acquired:
            logger.info("Skipping alert evaluation because another monitoring pipeline run is active")
            return
        with timed_phase(logger, "evaluate", "alerts"):
            await evaluate_alerts(db, commit=False)
        with timed_phase(logger, "commit", "alerts"):
            await db.commit()


async def _run_cleanup_job_inner(db) -> None:
    """Run cleanup job inner for scheduled monitoring execution."""
    async with _timed_guard(wait=False, scope="cleanup") as acquired:
        if not acquired:
            logger.info("Skipping retention cleanup because another cleanup run is active")
            return
        with timed_phase(logger, "cleanup_monitoring", "cleanup"):
            await cleanup_monitoring_data(db)
        with timed_phase(logger, "cleanup_auth", "cleanup"):
            await cleanup_auth_data(db)


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
