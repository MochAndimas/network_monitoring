"""Provide business services that coordinate repositories and domain workflows for the network monitoring project."""

from __future__ import annotations

import json
import logging
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.time import utcnow
from ..models.scheduler_job_status import SchedulerJobStatus


request_id_context: ContextVar[str] = ContextVar("request_id", default="")
job_name_context: ContextVar[str] = ContextVar("job_name", default="")

_http_request_count = Counter()
_http_request_errors = Counter()
_http_request_duration_ms = Counter()
_scheduler_job_runs = Counter()
_scheduler_job_failures = Counter()
_scheduler_job_duration_ms = Counter()
_exception_count = Counter()


class JsonLogFormatter(logging.Formatter):
    """Represent json log formatter behavior and data for business services that coordinate repositories and domain workflows.

    Inherits from `logging.Formatter` to match the surrounding framework or persistence model.
    """
    def format(self, record: logging.LogRecord) -> str:
        """Format the requested operation for business services that coordinate repositories and domain workflows.

        Args:
            record: record value used by this routine (type `logging.LogRecord`).

        Returns:
            `str` result produced by the routine.
        """
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(""),
            "job_name": job_name_context.get(""),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_structured_logging() -> None:
    """Handle configure structured logging for business services that coordinate repositories and domain workflows.

    Returns:
        None. The routine is executed for its side effects.
    """
    root_logger = logging.getLogger()
    formatter: logging.Formatter
    if settings.log_as_json:
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)


@contextmanager
def request_logging_context(request_id: str):
    """Handle request logging context for business services that coordinate repositories and domain workflows.

    Args:
        request_id: request id value used by this routine (type `str`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    token = request_id_context.set(request_id)
    try:
        yield
    finally:
        request_id_context.reset(token)


@contextmanager
def job_logging_context(job_name: str):
    """Handle job logging context for business services that coordinate repositories and domain workflows.

    Args:
        job_name: job name value used by this routine (type `str`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    token = job_name_context.set(job_name)
    try:
        yield
    finally:
        job_name_context.reset(token)


def normalized_http_metric_path(*, path: str, route_path: str | None = None) -> str:
    """Handle normalized http metric path for business services that coordinate repositories and domain workflows.

    Args:
        path: path keyword value used by this routine (type `str`).
        route_path: route path keyword value used by this routine (type `str | None`, optional).

    Returns:
        `str` result produced by the routine.
    """
    normalized_route = str(route_path or "").strip()
    if normalized_route:
        return normalized_route
    normalized_path = str(path or "").strip()
    return normalized_path or "/unknown"


def record_http_request(*, path: str, method: str, status_code: int, duration_ms: float, route_path: str | None = None) -> None:
    """Record http request for business services that coordinate repositories and domain workflows.

    Args:
        path: path keyword value used by this routine (type `str`).
        method: method keyword value used by this routine (type `str`).
        status_code: status code keyword value used by this routine (type `int`).
        duration_ms: duration ms keyword value used by this routine (type `float`).
        route_path: route path keyword value used by this routine (type `str | None`, optional).

    Returns:
        None. The routine is executed for its side effects.
    """
    metric_path = normalized_http_metric_path(path=path, route_path=route_path)
    key = (method.upper(), metric_path, str(status_code))
    _http_request_count[key] += 1
    _http_request_duration_ms[(method.upper(), metric_path)] += int(duration_ms)
    if status_code >= 500:
        _http_request_errors[(method.upper(), metric_path)] += 1


def record_exception(*, source: str) -> None:
    """Record exception for business services that coordinate repositories and domain workflows.

    Args:
        source: source keyword value used by this routine (type `str`).

    Returns:
        None. The routine is executed for its side effects.
    """
    _exception_count[source] += 1


async def mark_scheduler_job_started(db: AsyncSession, *, job_name: str) -> None:
    """Handle mark scheduler job started for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        job_name: job name keyword value used by this routine (type `str`).

    Returns:
        None. The routine is executed for its side effects.
    """
    status = await _get_or_create_scheduler_job_status(db, job_name=job_name)
    status.last_started_at = utcnow()
    status.is_running = True
    status.updated_at = utcnow()
    await db.commit()


async def mark_scheduler_job_succeeded(db: AsyncSession, *, job_name: str, duration_ms: float) -> None:
    """Handle mark scheduler job succeeded for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        job_name: job name keyword value used by this routine (type `str`).
        duration_ms: duration ms keyword value used by this routine (type `float`).

    Returns:
        None. The routine is executed for its side effects.
    """
    status = await _get_or_create_scheduler_job_status(db, job_name=job_name)
    now = utcnow()
    status.last_finished_at = now
    status.last_succeeded_at = now
    status.last_duration_ms = duration_ms
    status.consecutive_failures = 0
    status.last_error = None
    status.is_running = False
    status.updated_at = now
    _scheduler_job_runs[job_name] += 1
    _scheduler_job_duration_ms[job_name] += int(duration_ms)
    await db.commit()


async def mark_scheduler_job_failed(db: AsyncSession, *, job_name: str, duration_ms: float, error: str) -> None:
    """Handle mark scheduler job failed for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        job_name: job name keyword value used by this routine (type `str`).
        duration_ms: duration ms keyword value used by this routine (type `float`).
        error: error keyword value used by this routine (type `str`).

    Returns:
        None. The routine is executed for its side effects.
    """
    status = await _get_or_create_scheduler_job_status(db, job_name=job_name)
    now = utcnow()
    status.last_finished_at = now
    status.last_failed_at = now
    status.last_duration_ms = duration_ms
    status.consecutive_failures += 1
    status.last_error = error[:500]
    status.is_running = False
    status.updated_at = now
    _scheduler_job_runs[job_name] += 1
    _scheduler_job_failures[job_name] += 1
    _scheduler_job_duration_ms[job_name] += int(duration_ms)
    record_exception(source=f"scheduler:{job_name}")
    await db.commit()


async def list_scheduler_job_statuses(db: AsyncSession) -> list[SchedulerJobStatus]:
    """Return a list of scheduler job statuses for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).

    Returns:
        `list[SchedulerJobStatus]` result produced by the routine.
    """
    rows = await db.scalars(select(SchedulerJobStatus).order_by(SchedulerJobStatus.job_name.asc()))
    return list(rows.all())


def scheduler_job_is_stale(job: SchedulerJobStatus) -> bool:
    """Handle scheduler job is stale for business services that coordinate repositories and domain workflows.

    Args:
        job: job value used by this routine (type `SchedulerJobStatus`).

    Returns:
        `bool` result produced by the routine.
    """
    expected_interval = _expected_scheduler_interval_seconds(job.job_name)
    if expected_interval is None:
        return False
    last_reference = job.last_finished_at or job.last_started_at or job.updated_at
    stale_after_seconds = max(expected_interval * max(settings.scheduler_job_stale_factor, 1), 60)
    return last_reference <= utcnow() - timedelta(seconds=stale_after_seconds)


def build_scheduler_operational_alerts(job_statuses: list[SchedulerJobStatus]) -> list[dict]:
    """Build scheduler operational alerts for business services that coordinate repositories and domain workflows.

    Args:
        job_statuses: job statuses value used by this routine (type `list[SchedulerJobStatus]`).

    Returns:
        `list[dict]` result produced by the routine.
    """
    alerts: list[dict] = []
    for job in job_statuses:
        if job.consecutive_failures > 0:
            alerts.append(
                {
                    "job_name": job.job_name,
                    "severity": "critical" if job.consecutive_failures >= 3 else "warning",
                    "reason": "job_failures",
                    "message": f"{job.job_name} has {job.consecutive_failures} consecutive failures",
                    "last_error": job.last_error,
                }
            )
        elif scheduler_job_is_stale(job):
            alerts.append(
                {
                    "job_name": job.job_name,
                    "severity": "warning",
                    "reason": "job_stale",
                    "message": f"{job.job_name} heartbeat is stale",
                    "last_error": job.last_error,
                }
            )
    return alerts


def render_prometheus_metrics(*, database_up: bool, scheduler_alert_count: int, scheduler_statuses: list[SchedulerJobStatus]) -> str:
    """Render prometheus metrics for business services that coordinate repositories and domain workflows.

    Args:
        database_up: database up keyword value used by this routine (type `bool`).
        scheduler_alert_count: scheduler alert count keyword value used by this routine (type `int`).
        scheduler_statuses: scheduler statuses keyword value used by this routine (type `list[SchedulerJobStatus]`).

    Returns:
        `str` result produced by the routine.
    """
    lines = [
        "# HELP network_monitoring_database_up Database connectivity status",
        "# TYPE network_monitoring_database_up gauge",
        f"network_monitoring_database_up {1 if database_up else 0}",
        "# HELP network_monitoring_scheduler_operational_alerts Active operational alerts for scheduler jobs",
        "# TYPE network_monitoring_scheduler_operational_alerts gauge",
        f"network_monitoring_scheduler_operational_alerts {scheduler_alert_count}",
    ]
    for (method, path, status_code), count in sorted(_http_request_count.items()):
        lines.append(
            f'network_monitoring_http_requests_total{{method="{method}",path="{path}",status="{status_code}"}} {count}'
        )
    for (method, path), total_ms in sorted(_http_request_duration_ms.items()):
        lines.append(
            f'network_monitoring_http_request_duration_ms_sum{{method="{method}",path="{path}"}} {total_ms}'
        )
    for source, count in sorted(_exception_count.items()):
        lines.append(f'network_monitoring_exceptions_total{{source="{source}"}} {count}')
    for job in scheduler_statuses:
        lines.append(
            f'network_monitoring_scheduler_job_consecutive_failures{{job_name="{job.job_name}"}} {job.consecutive_failures}'
        )
        lines.append(
            f'network_monitoring_scheduler_job_running{{job_name="{job.job_name}"}} {1 if job.is_running else 0}'
        )
        lines.append(
            f'network_monitoring_scheduler_job_stale{{job_name="{job.job_name}"}} {1 if scheduler_job_is_stale(job) else 0}'
        )
        if job.last_duration_ms is not None:
            lines.append(
                f'network_monitoring_scheduler_job_last_duration_ms{{job_name="{job.job_name}"}} {job.last_duration_ms:.2f}'
            )
    return "\n".join(lines) + "\n"


async def _get_or_create_scheduler_job_status(db: AsyncSession, *, job_name: str) -> SchedulerJobStatus:
    """Return or create scheduler job status for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        job_name: job name keyword value used by this routine (type `str`).

    Returns:
        `SchedulerJobStatus` result produced by the routine.
    """
    status = await db.scalar(select(SchedulerJobStatus).where(SchedulerJobStatus.job_name == job_name))
    if status is None:
        status = SchedulerJobStatus(job_name=job_name)
        db.add(status)
        await db.flush()
    return status


def _expected_scheduler_interval_seconds(job_name: str) -> int | None:
    """Handle the internal expected scheduler interval seconds helper logic for business services that coordinate repositories and domain workflows.

    Args:
        job_name: job name value used by this routine (type `str`).

    Returns:
        `int | None` result produced by the routine.
    """
    mapping = {
        "internet_checks": settings.scheduler_interval_internet_seconds,
        "device_checks": settings.scheduler_interval_device_seconds,
        "server_checks": settings.scheduler_interval_server_seconds,
        "mikrotik_checks": settings.scheduler_interval_mikrotik_seconds,
        "alert_evaluation": settings.scheduler_interval_alert_seconds,
        "retention_cleanup": settings.scheduler_cleanup_interval_hours * 3600,
    }
    return mapping.get(job_name)
