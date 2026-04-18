from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...repositories.device_repository import DeviceRepository
from ...services.monitoring_service import utcnow
from ..helpers import bounded_gather, build_ping_metric, build_ping_quality_metrics, collect_ping_samples, latest_successful_ping

try:
    from librouteros import connect
except ImportError:  # pragma: no cover - dependency is declared but kept defensive
    connect = None


logger = logging.getLogger("network_monitoring.mikrotik")


async def run_mikrotik_checks(db: AsyncSession) -> list[dict]:
    devices = await DeviceRepository(db).list_by_type("mikrotik", active_only=True)
    metrics: list[dict] = [
        metric
        for device_metrics in await bounded_gather([_build_ping_metrics(device.id, device.ip_address) for device in devices])
        for metric in device_metrics
    ]

    if not devices or not settings.mikrotik_host or connect is None:
        return metrics

    api = None
    try:
        api = await asyncio.to_thread(
            connect,
            host=settings.mikrotik_host,
            username=settings.mikrotik_username,
            password=settings.mikrotik_password,
        )
        resources = await asyncio.to_thread(lambda: list(api.path("system", "resource")))
        interfaces = await asyncio.to_thread(lambda: list(api.path("interface").select("running")))
        resource = resources[0] if resources else {}
        checked_at = utcnow()
        target_device = devices[0]
        running_count = sum(1 for item in interfaces if item.get("running"))

        metrics.extend(
            [
                {
                    "device_id": target_device.id,
                    "metric_name": "cpu_percent",
                    "metric_value": str(resource.get("cpu-load", 0)),
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "memory_percent",
                    "metric_value": _mikrotik_memory_percent(resource),
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "interfaces_running",
                    "metric_value": str(running_count),
                    "status": "ok",
                    "unit": "count",
                    "checked_at": checked_at,
                },
            ]
        )
    except Exception:
        logger.exception("Mikrotik API check failed for host %s", settings.mikrotik_host)
        checked_at = utcnow()
        target_device = devices[0]
        metrics.append(
            {
                "device_id": target_device.id,
                "metric_name": "mikrotik_api",
                "metric_value": "connection_failed",
                "status": "error",
                "unit": None,
                "checked_at": checked_at,
            }
        )
    finally:
        if api is not None:
            await asyncio.to_thread(api.close)

    return metrics


async def _build_ping_metrics(device_id: int, ip_address: str) -> list[dict]:
    samples = await collect_ping_samples(ip_address)
    return [
        build_ping_metric(device_id, latest_successful_ping(samples)),
        *build_ping_quality_metrics(device_id, samples),
    ]


def _mikrotik_memory_percent(resource: dict) -> str:
    total = int(resource.get("total-memory", 0) or 0)
    free = int(resource.get("free-memory", 0) or 0)
    if total <= 0:
        return "0"
    used_percent = ((total - free) / total) * 100
    return f"{used_percent:.2f}"
