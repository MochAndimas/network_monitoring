"""Define module logic for `backend/app/monitors/device/service.py`.

This module contains project-specific implementation details.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories.device_repository import DeviceRepository
from ..helpers import bounded_gather, build_ping_metric, build_ping_quality_metrics, collect_ping_samples, latest_successful_ping, safe_ping
from .printer_snmp import collect_printer_snmp_metrics


DEVICE_TYPES = ["nvr", "switch", "access_point", "voip", "printer"]
QUALITY_CHECK_TYPES = {"access_point", "switch", "voip", "printer"}


async def run_device_checks(db: AsyncSession) -> list[dict]:
    """Run device checks as part of monitoring collection workflows.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    devices = await DeviceRepository(db).list_by_types(DEVICE_TYPES, active_only=True)
    return [
        metric
        for device_metrics in await bounded_gather([_build_device_metrics(device) for device in devices])
        for metric in device_metrics
    ]


async def _build_device_metrics(device) -> list[dict]:
    """Build device metrics.

    Args:
        device: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    if device.device_type == "printer":
        samples = await collect_ping_samples(device.ip_address)
        printer_snmp_metrics = await collect_printer_snmp_metrics(device.id, device.ip_address)
        return [
            build_ping_metric(device.id, latest_successful_ping(samples)),
            *build_ping_quality_metrics(device.id, samples),
            *printer_snmp_metrics,
        ]

    if device.device_type in QUALITY_CHECK_TYPES:
        samples = await collect_ping_samples(device.ip_address)
        return [
            build_ping_metric(device.id, latest_successful_ping(samples)),
            *build_ping_quality_metrics(device.id, samples),
        ]

    return [build_ping_metric(device.id, await safe_ping(device.ip_address))]
