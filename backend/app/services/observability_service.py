"""Define module logic for `backend/app/services/observability_service.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.time import utcnow
from ..models.scheduler_job_status import SchedulerJobStatus

try:  # pragma: no cover - optional dependency wiring
    from prometheus_client import CollectorRegistry, Counter as PromCounter, Summary, generate_latest, multiprocess
except ImportError:  # pragma: no cover - fallback path when dependency is unavailable
    CollectorRegistry = None
    PromCounter = None
    Summary = None
    generate_latest = None
    multiprocess = None


request_id_context: ContextVar[str] = ContextVar("request_id", default="")
job_name_context: ContextVar[str] = ContextVar("job_name", default="")

_http_request_count = Counter()
_http_request_errors = Counter()
_http_request_duration_ms = Counter()
_scheduler_job_runs = Counter()
_scheduler_job_failures = Counter()
_scheduler_job_duration_ms = Counter()
_exception_count = Counter()
_api_payload_request_count = Counter()
_api_payload_rows = Counter()
_api_payload_total_rows = Counter()
_api_payload_sampled = Counter()

_prometheus_multiproc_dir = str(os.getenv("PROMETHEUS_MULTIPROC_DIR") or "").strip()
_prometheus_multiprocess_enabled = bool(
    _prometheus_multiproc_dir and PromCounter is not None and Summary is not None and multiprocess is not None
)

if _prometheus_multiprocess_enabled:
    _prom_http_request_count = PromCounter(
        "network_monitoring_http_requests",
        "HTTP requests processed by the application",
        ["method", "path", "status"],
    )
    _prom_http_request_duration_ms = Summary(
        "network_monitoring_http_request_duration_ms",
        "Sum of HTTP request duration in milliseconds",
        ["method", "path"],
    )
    _prom_http_request_errors = PromCounter(
        "network_monitoring_http_request_errors",
        "HTTP requests that ended with status >= 500",
        ["method", "path"],
    )
    _prom_api_payload_request_count = PromCounter(
        "network_monitoring_api_payload_requests",
        "Payload responses observed by endpoint and scope",
        ["endpoint", "scope"],
    )
    _prom_api_payload_rows = PromCounter(
        "network_monitoring_api_payload_rows",
        "Rows returned in payload sections",
        ["endpoint", "scope", "section"],
    )
    _prom_api_payload_total_rows = Summary(
        "network_monitoring_api_payload_total_rows",
        "Total rows represented by payload sections",
        ["endpoint", "scope", "section"],
    )
    _prom_api_payload_sampled = PromCounter(
        "network_monitoring_api_payload_sampled",
        "Payload sections that were sampled/paged",
        ["endpoint", "scope", "section"],
    )
    _prom_exception_count = PromCounter(
        "network_monitoring_exceptions",
        "Exceptions captured by source",
        ["source"],
    )
else:
    _prom_http_request_count = None
    _prom_http_request_duration_ms = None
    _prom_http_request_errors = None
    _prom_api_payload_request_count = None
    _prom_api_payload_rows = None
    _prom_api_payload_total_rows = None
    _prom_api_payload_sampled = None
    _prom_exception_count = None


class JsonLogFormatter(logging.Formatter):
    """Perform JsonLogFormatter.

    This class encapsulates related behavior and data for this domain area.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render a log record as JSON with request/job context enrichment.

        Args:
            record: Parameter input untuk routine ini.

        Returns:
            Nilai balik routine atau efek samping yang dihasilkan.

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
    """Configure structured JSON logging for API and worker processes.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

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
    """Build standard log context fields for one HTTP request.

    Args:
        request_id: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    token = request_id_context.set(request_id)
    try:
        yield
    finally:
        request_id_context.reset(token)


@contextmanager
def job_logging_context(job_name: str):
    """Build standard log context fields for one scheduler job.

    Args:
        job_name: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    token = job_name_context.set(job_name)
    try:
        yield
    finally:
        job_name_context.reset(token)


def normalized_http_metric_path(*, path: str, route_path: str | None = None) -> str:
    """Normalize raw HTTP paths into metric-friendly route templates.

    Args:
        path: Parameter input untuk routine ini.
        route_path: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    normalized_route = str(route_path or "").strip()
    if normalized_route:
        return normalized_route
    normalized_path = str(path or "").strip()
    return normalized_path or "/unknown"


def record_http_request(*, path: str, method: str, status_code: int, duration_ms: float, route_path: str | None = None) -> None:
    """Record HTTP request metrics including duration, status, and route labels.

    Args:
        path: Parameter input untuk routine ini.
        method: Parameter input untuk routine ini.
        status_code: Parameter input untuk routine ini.
        duration_ms: Parameter input untuk routine ini.
        route_path: Parameter input untuk routine ini.

    """
    metric_path = normalized_http_metric_path(path=path, route_path=route_path)
    key = (method.upper(), metric_path, str(status_code))
    _http_request_count[key] += 1
    _http_request_duration_ms[(method.upper(), metric_path)] += int(duration_ms)
    if _prom_http_request_count is not None and _prom_http_request_duration_ms is not None:
        _prom_http_request_count.labels(method.upper(), metric_path, str(status_code)).inc()
        _prom_http_request_duration_ms.labels(method.upper(), metric_path).observe(float(duration_ms))
    if status_code >= 500:
        _http_request_errors[(method.upper(), metric_path)] += 1
        if _prom_http_request_errors is not None:
            _prom_http_request_errors.labels(method.upper(), metric_path).inc()


def record_exception(*, source: str) -> None:
    """Record exception counters for observability metrics.

    Args:
        source: Parameter input untuk routine ini.

    """
    _exception_count[source] += 1
    if _prom_exception_count is not None:
        _prom_exception_count.labels(source).inc()


def record_api_payload_request(*, endpoint: str, scope: str) -> None:
    """Record API payload request counters for observability tracking.

    Args:
        endpoint: Parameter input untuk routine ini.
        scope: Parameter input untuk routine ini.

    """
    _api_payload_request_count[(str(endpoint or "/unknown"), str(scope or "unknown"))] += 1
    if _prom_api_payload_request_count is not None:
        _prom_api_payload_request_count.labels(str(endpoint or "/unknown"), str(scope or "unknown")).inc()


def record_api_payload_section(
    *,
    endpoint: str,
    scope: str,
    section: str,
    rows: int,
    total_rows: int | None = None,
    sampled: bool = False,
) -> None:
    """Record API payload section/item counters for observability tracking.

    Args:
        endpoint: Parameter input untuk routine ini.
        scope: Parameter input untuk routine ini.
        section: Parameter input untuk routine ini.
        rows: Parameter input untuk routine ini.
        total_rows: Parameter input untuk routine ini.
        sampled: Parameter input untuk routine ini.

    """
    metric_endpoint = str(endpoint or "/unknown")
    metric_scope = str(scope or "unknown")
    metric_section = str(section or "unknown")
    section_key = (metric_endpoint, metric_scope, metric_section)
    _api_payload_rows[section_key] += max(int(rows), 0)
    if _prom_api_payload_rows is not None:
        _prom_api_payload_rows.labels(metric_endpoint, metric_scope, metric_section).inc(max(int(rows), 0))
    if total_rows is not None:
        _api_payload_total_rows[section_key] += max(int(total_rows), 0)
        if _prom_api_payload_total_rows is not None:
            _prom_api_payload_total_rows.labels(metric_endpoint, metric_scope, metric_section).observe(
                max(int(total_rows), 0)
            )
    if sampled:
        _api_payload_sampled[section_key] += 1
        if _prom_api_payload_sampled is not None:
            _prom_api_payload_sampled.labels(metric_endpoint, metric_scope, metric_section).inc()


async def mark_scheduler_job_started(db: AsyncSession, *, job_name: str, commit: bool = True) -> None:
    """Mark scheduler job as started and update running-state metadata.

    Args:
        db: Parameter input untuk routine ini.
        job_name: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    """
    status = await _get_or_create_scheduler_job_status(db, job_name=job_name)
    status.last_started_at = utcnow()
    status.is_running = True
    status.updated_at = utcnow()
    if commit:
        await db.commit()
    else:
        await db.flush()


async def mark_scheduler_job_succeeded(
    db: AsyncSession, *, job_name: str, duration_ms: float, commit: bool = True
) -> None:
    """Mark scheduler job as succeeded and persist duration/timestamp updates.

    Args:
        db: Parameter input untuk routine ini.
        job_name: Parameter input untuk routine ini.
        duration_ms: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

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
    if commit:
        await db.commit()
    else:
        await db.flush()


async def mark_scheduler_job_failed(
    db: AsyncSession, *, job_name: str, duration_ms: float, error: str, commit: bool = True
) -> None:
    """Mark scheduler job as failed and increment failure-state metadata.

    Args:
        db: Parameter input untuk routine ini.
        job_name: Parameter input untuk routine ini.
        duration_ms: Parameter input untuk routine ini.
        error: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

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
    if commit:
        await db.commit()
    else:
        await db.flush()


async def list_scheduler_job_statuses(db: AsyncSession) -> list[SchedulerJobStatus]:
    """List scheduler job status rows for observability dashboards.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    rows = await db.scalars(select(SchedulerJobStatus).order_by(SchedulerJobStatus.job_name.asc()))
    return list(rows.all())


def scheduler_job_is_stale(job: SchedulerJobStatus) -> bool:
    """Determine whether scheduler job heartbeat is stale beyond allowed interval.

    Args:
        job: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    expected_interval = _expected_scheduler_interval_seconds(job.job_name)
    if expected_interval is None:
        return False
    last_reference = job.last_finished_at or job.last_started_at or job.updated_at
    stale_after_seconds = max(expected_interval * max(settings.scheduler_job_stale_factor, 1), 60)
    return last_reference <= utcnow() - timedelta(seconds=stale_after_seconds)


def build_scheduler_operational_alerts(job_statuses: list[SchedulerJobStatus]) -> list[dict]:
    """Build operational alert payloads from scheduler job status state.

    Args:
        job_statuses: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

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
    """Render in-memory observability counters in Prometheus text format.

    Args:
        database_up: Parameter input untuk routine ini.
        scheduler_alert_count: Parameter input untuk routine ini.
        scheduler_statuses: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    lines = []
    if _prometheus_multiprocess_enabled and CollectorRegistry is not None and generate_latest is not None and multiprocess is not None:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        lines.extend(generate_latest(registry).decode("utf-8").splitlines())
    lines.extend(
        [
        "# HELP network_monitoring_database_up Database connectivity status",
        "# TYPE network_monitoring_database_up gauge",
        f"network_monitoring_database_up {1 if database_up else 0}",
        "# HELP network_monitoring_scheduler_operational_alerts Active operational alerts for scheduler jobs",
        "# TYPE network_monitoring_scheduler_operational_alerts gauge",
        f"network_monitoring_scheduler_operational_alerts {scheduler_alert_count}",
        ]
    )
    if not _prometheus_multiprocess_enabled:
        for (method, path, status_code), count in sorted(_http_request_count.items()):
            lines.append(
                f'network_monitoring_http_requests_total{{method="{method}",path="{path}",status="{status_code}"}} {count}'
            )
        for (method, path), total_ms in sorted(_http_request_duration_ms.items()):
            lines.append(
                f'network_monitoring_http_request_duration_ms_sum{{method="{method}",path="{path}"}} {total_ms}'
            )
        for (endpoint, scope), count in sorted(_api_payload_request_count.items()):
            lines.append(
                f'network_monitoring_api_payload_requests_total{{endpoint="{endpoint}",scope="{scope}"}} {count}'
            )
        for (endpoint, scope, section), count in sorted(_api_payload_rows.items()):
            lines.append(
                "network_monitoring_api_payload_rows_total"
                f'{{endpoint="{endpoint}",scope="{scope}",section="{section}"}} {count}'
            )
        for (endpoint, scope, section), count in sorted(_api_payload_total_rows.items()):
            lines.append(
                "network_monitoring_api_payload_total_rows_sum"
                f'{{endpoint="{endpoint}",scope="{scope}",section="{section}"}} {count}'
            )
        for (endpoint, scope, section), count in sorted(_api_payload_sampled.items()):
            lines.append(
                "network_monitoring_api_payload_sampled_total"
                f'{{endpoint="{endpoint}",scope="{scope}",section="{section}"}} {count}'
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
    """Retrieve or create scheduler job status.

    Args:
        db: Parameter input untuk routine ini.
        job_name: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    status = await db.scalar(select(SchedulerJobStatus).where(SchedulerJobStatus.job_name == job_name))
    if status is None:
        status = SchedulerJobStatus(job_name=job_name)
        db.add(status)
        await db.flush()
    return status


def _expected_scheduler_interval_seconds(job_name: str) -> int | None:
    """Perform expected scheduler interval seconds.

    Args:
        job_name: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

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
