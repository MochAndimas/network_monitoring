from ..core.config import settings
from ..db.session import SessionLocal
from ..alerting.engine import evaluate_alerts
from ..monitors.device.service import run_device_checks
from ..monitors.internet.service import run_internet_checks
from ..monitors.mikrotik.service import run_mikrotik_checks
from ..monitors.server.service import run_server_checks
from ..services.monitoring_service import persist_metrics
from ..services.retention_service import cleanup_monitoring_data


def register_jobs(scheduler) -> None:
    scheduler.add_job(
        run_internet_job,
        "interval",
        seconds=settings.scheduler_interval_internet_seconds,
        id="internet_checks",
        replace_existing=True,
    )
    scheduler.add_job(
        run_device_job,
        "interval",
        seconds=settings.scheduler_interval_device_seconds,
        id="device_checks",
        replace_existing=True,
    )
    scheduler.add_job(
        run_server_job,
        "interval",
        seconds=settings.scheduler_interval_server_seconds,
        id="server_checks",
        replace_existing=True,
    )
    scheduler.add_job(
        run_mikrotik_job,
        "interval",
        seconds=settings.scheduler_interval_mikrotik_seconds,
        id="mikrotik_checks",
        replace_existing=True,
    )
    scheduler.add_job(
        run_alert_job,
        "interval",
        seconds=settings.scheduler_interval_alert_seconds,
        id="alert_evaluation",
        replace_existing=True,
    )
    scheduler.add_job(
        run_cleanup_job,
        "interval",
        hours=settings.scheduler_cleanup_interval_hours,
        id="retention_cleanup",
        replace_existing=True,
    )


def run_internet_job() -> None:
    _persist_runner(run_internet_checks)


def run_device_job() -> None:
    _persist_runner(run_device_checks)


def run_server_job() -> None:
    _persist_runner(run_server_checks)


def run_mikrotik_job() -> None:
    _persist_runner(run_mikrotik_checks)


def run_alert_job() -> None:
    with SessionLocal() as db:
        evaluate_alerts(db)


def run_cleanup_job() -> None:
    with SessionLocal() as db:
        cleanup_monitoring_data(db)


def _persist_runner(runner) -> None:
    with SessionLocal() as db:
        persist_metrics(db, runner(db))
