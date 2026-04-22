"""Provide business services that coordinate repositories and domain workflows for the network monitoring project."""

from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.metric_repository import MetricRepository


logger = logging.getLogger("network_monitoring.service")

async def persist_metrics(db: AsyncSession, metrics: list[dict]) -> list:
    """Handle persist metrics for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        metrics: metrics value used by this routine (type `list[dict]`).

    Returns:
        `list` result produced by the routine.
    """
    return await MetricRepository(db).create_metrics(metrics)


async def build_dashboard_summary(db: AsyncSession) -> dict:
    """Build dashboard summary for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).

    Returns:
        `dict` result produced by the routine.
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
    """Handle status rollup from counts for business services that coordinate repositories and domain workflows.

    Args:
        status_counts: status counts value used by this routine (type `dict[str, int] | None`).

    Returns:
        `str` result produced by the routine.
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
