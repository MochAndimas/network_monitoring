"""Service-layer workflows for run cycle service."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..bandwidth.discovery import InventoryMetricBatch
from ..db.session import SessionLocal
from ..monitors.device.service import run_device_checks
from ..monitors.internet.service import run_internet_checks
from ..monitors.mikrotik.service import run_mikrotik_checks
from ..monitors.server.service import run_server_checks
from ..services.operational_alert_service import evaluate_operational_alerts as evaluate_alerts
from .collector_ownership import device_collector_ownership
from .monitoring_service import persist_metrics

logger = logging.getLogger("network_monitoring.run_cycle")


MonitorRunner = Callable[[AsyncSession], Awaitable[list[dict]]]


async def run_monitoring_cycle(
    db: AsyncSession,
    *,
    runners: tuple[MonitorRunner, ...] | None = None,
    collector_sessions: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Run collectors, persist metrics, and evaluate alerts in one transaction."""
    started_at = perf_counter()
    runner_results = (
        await collect_monitoring_metrics_by_runner()
        if runners is None and collector_sessions is None
        else await collect_monitoring_metrics_by_runner(runners=runners, collector_sessions=collector_sessions)
    )

    async with db.begin():
        metrics_collected = 0
        for runner_metrics in runner_results:
            has_inventory = isinstance(runner_metrics, InventoryMetricBatch) and bool(runner_metrics.snapshots)
            if not runner_metrics and not has_inventory:
                continue
            persisted = await persist_metrics(db, runner_metrics, commit=False)
            metrics_collected += len(persisted)
        alert_events = await evaluate_alerts(db, commit=False)

    result = {
        "metrics_collected": metrics_collected,
        "alerts_created": sum(1 for event in alert_events if event["action"] == "created"),
        "alerts_resolved": sum(1 for event in alert_events if event["action"] == "resolved"),
        "incidents_created": sum(1 for event in alert_events if event.get("incident_action") == "created"),
        "incidents_resolved": sum(1 for event in alert_events if event.get("incident_action") == "resolved"),
    }
    logger.info(
        "run_cycle_completed duration_ms=%.2f metrics=%s alerts_created=%s alerts_resolved=%s incidents_created=%s incidents_resolved=%s",
        (perf_counter() - started_at) * 1000,
        result["metrics_collected"],
        result["alerts_created"],
        result["alerts_resolved"],
        result["incidents_created"],
        result["incidents_resolved"],
    )
    return result


async def collect_monitoring_metrics() -> list[dict]:
    """Collect metrics from all configured monitor runners concurrently."""
    runner_results = await collect_monitoring_metrics_by_runner()
    metrics = [metric for batch in runner_results for metric in batch]
    snapshots = tuple(
        snapshot for batch in runner_results if isinstance(batch, InventoryMetricBatch) for snapshot in batch.snapshots
    )
    return InventoryMetricBatch(metrics, snapshots) if snapshots else metrics


async def collect_monitoring_metrics_by_runner(
    *,
    runners: tuple[MonitorRunner, ...] | None = None,
    collector_sessions: async_sessionmaker[AsyncSession] | None = None,
) -> list[list[dict]]:
    """Collect metrics grouped by monitor runner to avoid large flatten buffers."""
    return await asyncio.gather(
        *[
            _collect_runner_metrics(runner, session_factory=collector_sessions)
            for runner in (_monitor_runners() if runners is None else runners)
        ]
    )


async def _collect_runner_metrics(
    runner: MonitorRunner, *, session_factory: async_sessionmaker[AsyncSession] | None = None
) -> list[dict]:
    """Run one monitor collector with its own database session."""
    started_at = perf_counter()
    async with (session_factory or SessionLocal)() as db:
        metrics = await runner(db)
    logger.info(
        "monitor_runner_completed runner=%s duration_ms=%.2f metrics=%s",
        runner.__name__,
        (perf_counter() - started_at) * 1000,
        len(metrics),
    )
    return metrics


def _monitor_runners() -> tuple[MonitorRunner, ...]:
    """Agents run their device collector; central owns the other domains."""
    if device_collector_ownership().site is not None:
        return (_run_owned_device_checks,)
    return (
        run_internet_checks,
        _run_owned_device_checks,
        run_server_checks,
        run_mikrotik_checks,
    )


async def _run_owned_device_checks(db: AsyncSession) -> list[dict]:
    """Apply the same site ownership as the scheduled device collector."""
    ownership = device_collector_ownership()
    return await run_device_checks(db, site=ownership.site, excluded_sites=set(ownership.excluded_sites))
