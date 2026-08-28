"""Monitoring collector helpers for service."""

from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories.device_repository import DeviceRepository
from ..helpers import bounded_gather
from .adapters import NasSnmpCollector, PrinterSnmpCollector, collector_for_device_type
from .nas_snmp import collect_nas_snmp_metrics
from .printer_snmp import collect_printer_snmp_metrics


DEVICE_TYPES = ["nas", "nvr", "switch", "access_point", "voip", "printer"]


async def run_device_checks(db: AsyncSession, *, site: str | None = None, excluded_sites: set[str] | None = None) -> list[dict]:
    """Run device checks for monitoring collection."""
    devices = await DeviceRepository(db).list_by_types(DEVICE_TYPES, active_only=True, site=site, excluded_sites=excluded_sites)
    return [
        metric
        for device_metrics in await bounded_gather([_build_device_metrics(device) for device in devices])
        for metric in device_metrics
    ]


async def _build_device_metrics(device) -> list[dict]:
    """Build metrics through the adapter selected for this device type."""
    # Keep these dependencies injectable at the service boundary. Existing
    # tests and future vendor overrides can replace only the SNMP capability
    # without knowing the adapter's orchestration details.
    if device.device_type == "printer":
        return await PrinterSnmpCollector(collect_printer_snmp_metrics).collect(device)
    if device.device_type == "nas":
        return await NasSnmpCollector(collect_nas_snmp_metrics).collect(device)
    return await collector_for_device_type(device.device_type).collect(device)
