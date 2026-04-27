"""Define module logic for `backend/app/monitors/server/service.py`.

This module contains project-specific implementation details.
"""

import asyncio
import ipaddress
import logging

import psutil
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...repositories.device_repository import DeviceRepository
from ...core.time import utcnow
from ..helpers import bounded_gather, build_ping_metric, safe_ping


logger = logging.getLogger("network_monitoring.server")


async def run_server_checks(db: AsyncSession) -> list[dict]:
    """Run server checks as part of monitoring collection workflows.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    servers = await DeviceRepository(db).list_by_type("server", active_only=True)
    metrics: list[dict] = []
    if not servers:
        return metrics

    ping_metrics = await bounded_gather([safe_ping(server.ip_address) for server in servers])
    metrics.extend(build_ping_metric(server.id, latency) for server, latency in zip(servers, ping_metrics, strict=False))

    target_server = _resolve_server_resource_target(servers)
    if target_server is not None:
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
                    "device_id": target_server.id,
                    "metric_name": "cpu_percent",
                    "metric_value": f"{cpu_percent:.2f}",
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_server.id,
                    "metric_name": "memory_percent",
                    "metric_value": f"{memory_percent:.2f}",
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_server.id,
                    "metric_name": "disk_percent",
                    "metric_value": f"{disk_percent:.2f}",
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_server.id,
                    "metric_name": "boot_time_epoch",
                    "metric_value": f"{int(boot_time_epoch)}",
                    "status": "ok",
                    "unit": "epoch",
                    "checked_at": checked_at,
                },
            ]
        )

    return metrics


def _resolve_server_resource_target(servers: list):
    """Resolve server resource target.

    Args:
        servers: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    configured_ip = str(settings.server_resource_device_ip or "").strip()
    if configured_ip:
        for server in servers:
            if str(server.ip_address) == configured_ip:
                return server
        logger.warning(
            "Skipping server resource metrics because SERVER_RESOURCE_DEVICE_IP=%s does not match any active server",
            configured_ip,
        )
        return None

    if len(servers) == 1:
        return servers[0]

    loopback_servers = [server for server in servers if _is_loopback_ip(server.ip_address)]
    if len(loopback_servers) == 1:
        return loopback_servers[0]
    if len(loopback_servers) > 1:
        loopback_servers.sort(key=lambda item: str(item.name or "").lower())
        return loopback_servers[0]

    logger.info(
        "Skipping server resource metrics because there are %s active server devices and no SERVER_RESOURCE_DEVICE_IP override",
        len(servers),
    )
    return None


def _is_loopback_ip(value: str) -> bool:
    """Perform is loopback ip.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    try:
        return ipaddress.ip_address(str(value)).is_loopback
    except ValueError:
        return False
