"""Service-layer workflows for run cycle service."""

import asyncio
import logging
from time import perf_counter
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..alerting.engine import evaluate_alerts
from ..db.session import SessionLocal
from ..monitors.device.service import run_device_checks
from ..monitors.internet.service import run_internet_checks
from ..monitors.mikrotik.service import run_mikrotik_checks
from ..monitors.server.service import run_server_checks
from .monitoring_service import persist_metrics


logger = logging.getLogger("network_monitoring.run_cycle")


MonitorRunner = Callable[[AsyncSession], Awaitable[list[dict]]]


async def run_monitoring_cycle(db: AsyncSession) -> dict:
    """Run collectors, persist metrics, and evaluate alerts in one transaction."""
    started_at = perf_counter()
    runner_results = await collect_monitoring_metrics_by_runner()

    async with db.begin():
        metrics_collected = 0
        for runner_metrics in runner_results:
            if not runner_metrics:
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
    return [metric for metrics in runner_results for metric in metrics]


async def collect_monitoring_metrics_by_runner() -> list[list[dict]]:
    """Collect metrics grouped by monitor runner to avoid large flatten buffers."""
    return await asyncio.gather(*[_collect_runner_metrics(runner) for runner in _monitor_runners()])


async def _collect_runner_metrics(runner: MonitorRunner) -> list[dict]:
    """Run one monitor collector with its own database session."""
    started_at = perf_counter()
    async with SessionLocal() as db:
        metrics = await runner(db)
    logger.info(
        "monitor_runner_completed runner=%s duration_ms=%.2f metrics=%s",
        runner.__name__,
        (perf_counter() - started_at) * 1000,
        len(metrics),
    )
    return metrics


def _monitor_runners() -> tuple[MonitorRunner, ...]:
    """Return the monitor runner functions included in a full cycle."""
    return (
        run_internet_checks,
        run_device_checks,
        run_server_checks,
        run_mikrotik_checks,
    )
