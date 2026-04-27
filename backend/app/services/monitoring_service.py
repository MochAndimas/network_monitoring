"""Define module logic for `backend/app/services/monitoring_service.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.metric_repository import MetricRepository


logger = logging.getLogger("network_monitoring.service")

async def persist_metrics(db: AsyncSession, metrics: list[dict], *, commit: bool = True) -> list:
    """Persist one monitoring batch of metric samples.

    Args:
        db: Parameter input untuk routine ini.
        metrics: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return await MetricRepository(db).create_metrics(metrics, commit=commit)


async def build_dashboard_summary(db: AsyncSession) -> dict:
    """Build dashboard summary payload from latest monitoring data.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    started_at = perf_counter()
    grouped_statuses = await DeviceRepository(db).summarize_active_device_statuses()
    active_alerts = await AlertRepository(db).count_active_alerts()

    summary = {
        "internet_status": status_rollup_from_counts(grouped_statuses.get("internet_target")),
        "mikrotik_status": status_rollup_from_counts(grouped_statuses.get("mikrotik")),
        "server_status": status_rollup_from_counts(grouped_statuses.get("server")),
        "active_alerts": active_alerts,
    }
    logger.info(
        "build_dashboard_summary_completed duration_ms=%.2f internet=%s mikrotik=%s server=%s active_alerts=%s",
        (perf_counter() - started_at) * 1000,
        summary["internet_status"],
        summary["mikrotik_status"],
        summary["server_status"],
        summary["active_alerts"],
    )
    return summary


def status_rollup_from_counts(status_counts: dict[str, int] | None) -> str:
    """Compute health rollup label from aggregated status counters.

    Args:
        status_counts: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if not status_counts:
        return "unknown"

    normalized = {str(status).lower(): count for status, count in status_counts.items() if count}
    if not normalized:
        return "unknown"
    if any(status in {"down", "critical", "error"} for status in normalized):
        return "down"
    if any(status in {"warning", "degraded", "unavailable"} for status in normalized):
        return "warning"
    if all(status in {"up", "healthy", "ok"} for status in normalized):
        return "up"
    return next(iter(normalized))
