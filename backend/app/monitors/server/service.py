"""Provide monitoring collectors for network, device, server, and Mikrotik metrics for the network monitoring project."""

import asyncio

import psutil
from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories.device_repository import DeviceRepository
from ...core.time import utcnow
from ..helpers import bounded_gather, build_ping_metric, safe_ping


async def run_server_checks(db: AsyncSession) -> list[dict]:
    """Run server checks for monitoring collectors for network, device, server, and Mikrotik metrics. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).

    Returns:
        `list[dict]` result produced by the routine.
    """
    servers = await DeviceRepository(db).list_by_type("server", active_only=True)
    metrics: list[dict] = []
    if not servers:
        return metrics

    ping_metrics = await bounded_gather([safe_ping(server.ip_address) for server in servers])
    metrics.extend(build_ping_metric(server.id, latency) for server, latency in zip(servers, ping_metrics, strict=False))

    checked_at = utcnow()
    cpu_percent, memory_percent, disk_percent, boot_time_epoch = await asyncio.gather(
        asyncio.to_thread(psutil.cpu_percent, 0.1),
        asyncio.to_thread(lambda: psutil.virtual_memory().percent),
        asyncio.to_thread(lambda: psutil.disk_usage("/").percent),
        asyncio.to_thread(psutil.boot_time),
    )

    metrics.extend(
        [
            {
                "device_id": servers[0].id,
                "metric_name": "cpu_percent",
                "metric_value": f"{cpu_percent:.2f}",
                "status": "ok",
                "unit": "%",
                "checked_at": checked_at,
            },
            {
                "device_id": servers[0].id,
                "metric_name": "memory_percent",
                "metric_value": f"{memory_percent:.2f}",
                "status": "ok",
                "unit": "%",
                "checked_at": checked_at,
            },
            {
                "device_id": servers[0].id,
                "metric_name": "disk_percent",
                "metric_value": f"{disk_percent:.2f}",
                "status": "ok",
                "unit": "%",
                "checked_at": checked_at,
            },
            {
                "device_id": servers[0].id,
                "metric_name": "boot_time_epoch",
                "metric_value": f"{int(boot_time_epoch)}",
                "status": "ok",
                "unit": "epoch",
                "checked_at": checked_at,
            },
        ]
    )

    return metrics
