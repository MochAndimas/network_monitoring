from __future__ import annotations

import json
import logging
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from time import perf_counter

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
    def format(self, record: logging.LogRecord) -> str:
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
    token = request_id_context.set(request_id)
    try:
        yield
    finally:
        request_id_context.reset(token)


@contextmanager
def job_logging_context(job_name: str):
    token = job_name_context.set(job_name)
    try:
        yield
    finally:
        job_name_context.reset(token)


def record_http_request(*, path: str, method: str, status_code: int, duration_ms: float) -> None:
    key = (method.upper(), path, str(status_code))
    _http_request_count[key] += 1
    _http_request_duration_ms[(method.upper(), path)] += int(duration_ms)
    if status_code >= 500:
        _http_request_errors[(method.upper(), path)] += 1


def record_exception(*, source: str) -> None:
    _exception_count[source] += 1


async def mark_scheduler_job_started(db: AsyncSession, *, job_name: str) -> None:
    status = await _get_or_create_scheduler_job_status(db, job_name=job_name)
    status.last_started_at = utcnow()
    status.is_running = True
    status.updated_at = utcnow()
    await db.commit()


async def mark_scheduler_job_succeeded(db: AsyncSession, *, job_name: str, duration_ms: float) -> None:
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
    rows = await db.scalars(select(SchedulerJobStatus).order_by(SchedulerJobStatus.job_name.asc()))
    return list(rows.all())


def scheduler_job_is_stale(job: SchedulerJobStatus) -> bool:
    expected_interval = _expected_scheduler_interval_seconds(job.job_name)
    if expected_interval is None:
        return False
    last_reference = job.last_finished_at or job.last_started_at or job.updated_at
    stale_after_seconds = max(expected_interval * max(settings.scheduler_job_stale_factor, 1), 60)
    return last_reference <= utcnow() - timedelta(seconds=stale_after_seconds)


def build_scheduler_operational_alerts(job_statuses: list[SchedulerJobStatus]) -> list[dict]:
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
    status = await db.scalar(select(SchedulerJobStatus).where(SchedulerJobStatus.job_name == job_name))
    if status is None:
        status = SchedulerJobStatus(job_name=job_name)
        db.add(status)
        await db.flush()
    return status


def _expected_scheduler_interval_seconds(job_name: str) -> int | None:
    mapping = {
        "internet_checks": settings.scheduler_interval_internet_seconds,
        "device_checks": settings.scheduler_interval_device_seconds,
        "server_checks": settings.scheduler_interval_server_seconds,
        "mikrotik_checks": settings.scheduler_interval_mikrotik_seconds,
        "alert_evaluation": settings.scheduler_interval_alert_seconds,
        "retention_cleanup": settings.scheduler_cleanup_interval_hours * 3600,
    }
    return mapping.get(job_name)


@contextmanager
def timing_window():
    started = perf_counter()
    try:
        yield lambda: (perf_counter() - started) * 1000
    finally:
        pass
