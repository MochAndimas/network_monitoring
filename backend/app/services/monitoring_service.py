"""Service-layer workflows for monitoring service."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.metric_contracts import MetricWritePayload

from ..bandwidth.discovery import InventoryMetricBatch
from ..core.config import settings
from ..core.phase_timing import timed_phase
from ..models.metric import Metric
from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.metric_repository import MetricRepository
from .bandwidth_inventory_service import sync_inventory

logger = logging.getLogger("network_monitoring.service")


async def persist_metrics(
    db: AsyncSession,
    metrics: Sequence[MetricWritePayload | Mapping[str, Any]],
    *,
    commit: bool = True,
    repository_factory: Callable[[AsyncSession], MetricRepository] = MetricRepository,
) -> list[Metric]:
    """Persist a batch of collected metric payloads."""
    if isinstance(metrics, InventoryMetricBatch):
        # Fixed lock order for multi-router batches; all writes join the caller's
        # transaction. Failed collection never carries an authoritative snapshot.
        with timed_phase(logger, "metric_inventory_sync", "mikrotik"):
            for snapshot in sorted(metrics.snapshots, key=lambda item: item.router_id):
                await sync_inventory(
                    db, snapshot, max_observation_gap_seconds=settings.bandwidth_inventory_max_gap_seconds
                )
    persisted_metrics = await repository_factory(db).create_metrics(metrics, commit=commit)
    if commit and isinstance(metrics, InventoryMetricBatch) and not metrics:
        await db.commit()
    if persisted_metrics:
        from .dashboard_overview_service import invalidate_dashboard_overview_cache

        invalidate_dashboard_overview_cache()
    return persisted_metrics


async def build_dashboard_summary(db: AsyncSession) -> dict:
    """Build high-level status rollups for the dashboard summary endpoint."""
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
    """Collapse grouped status counts into a single health label."""
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
