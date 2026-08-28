"""Service-layer workflows for observability service."""

from __future__ import annotations

import json
import logging
import os
import platform
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.time import utcnow
from ..models.scheduler_job_status import SchedulerJobStatus

try:  # pragma: no cover - optional dependency wiring
    from prometheus_client import CollectorRegistry, Counter as PromCounter, Summary, generate_latest, multiprocess
except ImportError:  # pragma: no cover - fallback path when dependency is unavailable
    CollectorRegistry = None  # type: ignore[assignment, misc]
    PromCounter = None  # type: ignore[assignment, misc]
    Summary = None  # type: ignore[assignment, misc]
    generate_latest = None  # type: ignore[assignment]
    multiprocess = None  # type: ignore[assignment]


request_id_context: ContextVar[str] = ContextVar("request_id", default="")
job_name_context: ContextVar[str] = ContextVar("job_name", default="")

_http_request_count: Counter = Counter()
_http_request_errors: Counter = Counter()
_http_request_duration_ms: Counter = Counter()
_scheduler_job_runs: Counter = Counter()
_scheduler_job_failures: Counter = Counter()
_scheduler_job_duration_ms: Counter = Counter()
_exception_count: Counter = Counter()
_api_payload_request_count: Counter = Counter()
_api_payload_rows: Counter = Counter()
_api_payload_total_rows: Counter = Counter()
_api_payload_sampled: Counter = Counter()

_prometheus_multiproc_dir = str(os.getenv("PROMETHEUS_MULTIPROC_DIR") or "").strip()
_prometheus_multiprocess_enabled = bool(
    _prometheus_multiproc_dir and PromCounter is not None and Summary is not None and multiprocess is not None
)
_process_identity = {
    "pid": os.getpid(),
    "hostname": platform.node(),
    "prometheus_multiprocess_enabled": _prometheus_multiprocess_enabled,
    "prometheus_multiproc_dir": _prometheus_multiproc_dir,
    "web_concurrency": str(os.getenv("WEB_CONCURRENCY") or "").strip(),
}

if _prometheus_multiprocess_enabled:
    assert PromCounter is not None
    assert Summary is not None
    _prom_http_request_count: Any = PromCounter(
        "network_monitoring_http_requests",
        "HTTP requests processed by the application",
        ["method", "path", "status"],
    )
    _prom_http_request_duration_ms: Any = Summary(
        "network_monitoring_http_request_duration_ms",
        "Sum of HTTP request duration in milliseconds",
        ["method", "path"],
    )
    _prom_http_request_errors: Any = PromCounter(
        "network_monitoring_http_request_errors",
        "HTTP requests that ended with status >= 500",
        ["method", "path"],
    )
    _prom_api_payload_request_count: Any = PromCounter(
        "network_monitoring_api_payload_requests",
        "Payload responses observed by endpoint and scope",
        ["endpoint", "scope"],
    )
    _prom_api_payload_rows: Any = PromCounter(
        "network_monitoring_api_payload_rows",
        "Rows returned in payload sections",
        ["endpoint", "scope", "section"],
    )
    _prom_api_payload_total_rows: Any = Summary(
        "network_monitoring_api_payload_total_rows",
        "Total rows represented by payload sections",
        ["endpoint", "scope", "section"],
    )
    _prom_api_payload_sampled: Any = PromCounter(
        "network_monitoring_api_payload_sampled",
        "Payload sections that were sampled/paged",
        ["endpoint", "scope", "section"],
    )
    _prom_exception_count: Any = PromCounter(
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
    """Helper object used by service-layer workflows."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a log record as structured JSON."""
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_log_message(record.getMessage()),
            "request_id": request_id_context.get(""),
            "job_name": job_name_context.get(""),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


class RedactingFormatter(logging.Formatter):
    """Format plain-text logs with sensitive runtime values masked."""

    def format(self, record: logging.LogRecord) -> str:
        """Render a log record and mask secrets in the final message."""
        return redact_sensitive_log_message(super().format(record))


def redact_sensitive_log_message(message: str) -> str:
    """Mask configured secrets from log output."""
    redacted_message = str(message)
    telegram_settings = settings.telegram
    sensitive_values = {
        telegram_settings.bot_token: "[telegram_bot_token]",
        telegram_settings.chat_id: "[telegram_chat_id]",
    }
    for secret_value, replacement in sensitive_values.items():
        normalized_secret = str(secret_value or "").strip()
        if normalized_secret:
            redacted_message = redacted_message.replace(normalized_secret, replacement)
    return redacted_message


def configure_structured_logging() -> None:
    """Install JSON or redacting log formatters on existing handlers."""
    root_logger = logging.getLogger()
    formatter: logging.Formatter
    if settings.observability.log_as_json:
        formatter = JsonLogFormatter()
    else:
        formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)


@contextmanager
def request_logging_context(request_id: str):
    """Bind a request id to logs emitted within the context."""
    token = request_id_context.set(request_id)
    try:
        yield
    finally:
        request_id_context.reset(token)


@contextmanager
def job_logging_context(job_name: str):
    """Bind a scheduler job name to logs emitted within the context."""
    token = job_name_context.set(job_name)
    try:
        yield
    finally:
        job_name_context.reset(token)


def normalized_http_metric_path(*, path: str, route_path: str | None = None) -> str:
    """Return a low-cardinality path label for HTTP metrics."""
    normalized_route = str(route_path or "").strip()
    if normalized_route:
        return normalized_route
    normalized_path = str(path or "").strip()
    return normalized_path or "/unknown"


def record_http_request(*, path: str, method: str, status_code: int, duration_ms: float, route_path: str | None = None) -> None:
    """Record HTTP request counts, latency buckets, and Prometheus samples."""
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
    """Increment exception counters for a source area."""
    _exception_count[source] += 1
    if _prom_exception_count is not None:
        _prom_exception_count.labels(source).inc()


def record_api_payload_request(*, endpoint: str, scope: str) -> None:
    """Record that an API payload endpoint was requested."""
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
    """Record row counts and sampling state for one payload section."""
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


def build_observability_runtime_info() -> dict[str, object]:
    """Return process-local observability mode details for operational diagnostics."""
    return dict(_process_identity)


async def mark_scheduler_job_started(db: AsyncSession, *, job_name: str, commit: bool = True) -> None:
    """Store the start timestamp for a scheduler job run."""
    status = await _get_or_create_scheduler_job_status(db, job_name=job_name)
    status.last_started_at = utcnow()
    status.is_running = True
    status.updated_at = utcnow()
    if commit:
        await db.commit()
    else:
        await db.flush()


async def mark_scheduler_jobs_registered(
    db: AsyncSession,
    *,
    job_names: list[str],
    commit: bool = True,
) -> None:
    """Refresh scheduler heartbeats when a worker registers its jobs."""
    registered_at = utcnow()
    for job_name in sorted(set(job_names)):
        status = await _get_or_create_scheduler_job_status(db, job_name=job_name)
        status.is_running = False
        status.updated_at = registered_at
    if commit:
        await db.commit()
    else:
        await db.flush()


async def mark_scheduler_job_succeeded(
    db: AsyncSession, *, job_name: str, duration_ms: float, commit: bool = True
) -> None:
    """Store scheduler job success timing and reset failure counters."""
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
    """Store scheduler job failure details and increment failure counters."""
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
    """Return scheduler job status rows ordered by job name."""
    rows = await db.scalars(select(SchedulerJobStatus).order_by(SchedulerJobStatus.job_name.asc()))
    return list(rows.all())


def scheduler_job_is_stale(job: SchedulerJobStatus) -> bool:
    """Return scheduler job is stale used by service-layer code."""
    expected_interval = _expected_scheduler_interval_seconds(job.job_name)
    if expected_interval is None:
        return False
    references = [
        timestamp
        for timestamp in (job.last_finished_at, job.last_started_at, job.updated_at)
        if timestamp is not None
    ]
    if not references:
        return False
    last_reference = max(references)
    stale_after_seconds = max(expected_interval * max(settings.scheduler.job_stale_factor, 1), 60)
    return last_reference <= utcnow() - timedelta(seconds=stale_after_seconds)


def build_scheduler_job_health_rows(job_statuses: list[SchedulerJobStatus]) -> list[dict]:
    """Return scheduler timing health derived from configured job intervals."""
    now = utcnow()
    rows: list[dict] = []
    for job in job_statuses:
        expected_interval_seconds = _expected_scheduler_interval_seconds(job.job_name)
        references = [
            timestamp
            for timestamp in (job.last_finished_at, job.last_started_at, job.updated_at)
            if timestamp is not None
        ]
        last_heartbeat_at = max(references) if references else None
        heartbeat_age_seconds = (
            max((now - last_heartbeat_at).total_seconds(), 0.0) if last_heartbeat_at is not None else None
        )
        schedule_lag_seconds = (
            max(heartbeat_age_seconds - expected_interval_seconds, 0.0)
            if heartbeat_age_seconds is not None and expected_interval_seconds is not None
            else None
        )
        stale_after_seconds = (
            max(expected_interval_seconds * max(settings.scheduler.job_stale_factor, 1), 60)
            if expected_interval_seconds is not None
            else None
        )
        consecutive_failures = int(job.consecutive_failures or 0)
        if consecutive_failures > 0:
            state = "failing"
        elif scheduler_job_is_stale(job):
            state = "stale"
        elif job.is_running:
            state = "running"
        elif last_heartbeat_at is None:
            state = "no_data"
        else:
            state = "on_schedule"
        rows.append(
            {
                "job_name": job.job_name,
                "state": state,
                "expected_interval_seconds": expected_interval_seconds,
                "stale_after_seconds": stale_after_seconds,
                "last_heartbeat_at": last_heartbeat_at,
                "heartbeat_age_seconds": heartbeat_age_seconds,
                "schedule_lag_seconds": schedule_lag_seconds,
                "consecutive_failures": consecutive_failures,
                "last_duration_ms": job.last_duration_ms,
            }
        )
    return rows


def build_collector_health_rows(rows: list[dict]) -> list[dict]:
    """Add success-rate and actionable health state to collector rollups."""
    result: list[dict] = []
    for row in rows:
        samples = int(row.get("sample_count") or 0)
        success = int(row.get("success_count") or 0)
        timeouts = int(row.get("timeout_count") or 0)
        unsupported = int(row.get("unsupported_oid_count") or 0)
        rate = round((success / samples) * 100, 2) if samples else 0.0
        state = "healthy" if rate >= 99 else "degraded" if rate >= 90 else "failing"
        if unsupported:
            action = "OID tidak didukung; cek MIB/vendor dan capability device."
        elif timeouts:
            action = "Timeout; cek VPN/routing, ACL, dan reachability dari server monitoring."
        elif str(row.get("collector")) in {"printer_snmp", "nas_snmp"}:
            action = "Cek ACL UDP 161, community read-only, dan versi SNMP."
        elif str(row.get("collector")) == "mikrotik_api":
            action = "Cek VPN/routing, ACL API, dan credential RouterOS."
        else:
            action = "Cek host monitoring, VPN/routing, dan konfigurasi collector."
        result.append({**row, "success_rate_percent": rate, "state": state, "action": action})
    return result


def build_scheduler_operational_alerts(job_statuses: list[SchedulerJobStatus]) -> list[dict]:
    """Build operational alerts for stale or repeatedly failing scheduler jobs."""
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
    """Render internal counters in Prometheus text exposition format."""
    lines = []
    if _prometheus_multiprocess_enabled and CollectorRegistry is not None and generate_latest is not None and multiprocess is not None:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        lines.extend(generate_latest(registry).decode("utf-8").splitlines())
    lines.extend(
        [
        "# HELP network_monitoring_observability_multiprocess_enabled Prometheus multiprocess collection mode",
        "# TYPE network_monitoring_observability_multiprocess_enabled gauge",
        f"network_monitoring_observability_multiprocess_enabled {1 if _prometheus_multiprocess_enabled else 0}",
        "# HELP network_monitoring_observability_process_info Process-local observability runtime metadata",
        "# TYPE network_monitoring_observability_process_info gauge",
        (
            'network_monitoring_observability_process_info'
            f'{{pid="{os.getpid()}",hostname="{platform.node()}",'
            f'prometheus_multiproc_dir="{_prometheus_multiproc_dir}",'
            f'web_concurrency="{str(os.getenv("WEB_CONCURRENCY") or "").strip()}"}} 1'
        ),
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
    """Return get or create scheduler job status used by observability and health reporting."""
    status = await db.scalar(select(SchedulerJobStatus).where(SchedulerJobStatus.job_name == job_name))
    if status is None:
        status = SchedulerJobStatus(job_name=job_name)
        db.add(status)
        await db.flush()
    return status


def _expected_scheduler_interval_seconds(job_name: str) -> int | None:
    """Return expected scheduler interval seconds used by service-layer code."""
    scheduler_settings = settings.scheduler
    mapping = {
        "internet_checks": scheduler_settings.interval_internet_seconds,
        "device_checks": scheduler_settings.interval_device_seconds,
        "server_checks": scheduler_settings.interval_server_seconds,
        "mikrotik_checks": scheduler_settings.interval_mikrotik_seconds,
        "alert_evaluation": scheduler_settings.interval_alert_seconds,
        "retention_cleanup": scheduler_settings.cleanup_interval_hours * 3600,
    }
    return mapping.get(job_name)
