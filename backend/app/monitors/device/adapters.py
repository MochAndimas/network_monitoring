"""Device collector adapters with a small, vendor-neutral contract."""

from __future__ import annotations

from typing import Protocol

from ..helpers import build_ping_check_metrics, collect_ping_probe_samples
from .nas_snmp import collect_nas_snmp_metrics
from .printer_snmp import collect_printer_snmp_metrics


class DeviceCollectorAdapter(Protocol):
    """Collect normalized metric payloads for one device capability/vendor."""

    async def collect(self, device) -> list[dict]:
        """Return metric payloads that use the common monitoring contract."""
        ...


class PingOnlyCollector:
    """Collector for devices monitored only through ICMP reachability."""

    async def collect(self, device) -> list[dict]:
        return build_ping_check_metrics(device.id, await collect_ping_probe_samples(device.ip_address))


class PrinterSnmpCollector(PingOnlyCollector):
    """Collector that adds printer-vendor SNMP metrics after ICMP."""

    def __init__(self, snmp_collector=collect_printer_snmp_metrics) -> None:
        self._snmp_collector = snmp_collector

    async def collect(self, device) -> list[dict]:
        probes = await collect_ping_probe_samples(device.ip_address)
        snmp_metrics = await self._snmp_collector(device.id, device.ip_address)
        return [*build_ping_check_metrics(device.id, probes), *snmp_metrics]


class NasSnmpCollector(PingOnlyCollector):
    """Collector that adds NAS SNMP metrics after ICMP."""

    def __init__(self, snmp_collector=collect_nas_snmp_metrics) -> None:
        self._snmp_collector = snmp_collector

    async def collect(self, device) -> list[dict]:
        probes = await collect_ping_probe_samples(device.ip_address)
        snmp_metrics = await self._snmp_collector(device.id, device.ip_address)
        return [*build_ping_check_metrics(device.id, probes), *snmp_metrics]


DEVICE_COLLECTORS: dict[str, DeviceCollectorAdapter] = {
    "printer": PrinterSnmpCollector(),
    "nas": NasSnmpCollector(),
}
DEFAULT_DEVICE_COLLECTOR: DeviceCollectorAdapter = PingOnlyCollector()


def collector_for_device_type(device_type: str) -> DeviceCollectorAdapter:
    """Return the adapter for a type, falling back to standard ICMP checks."""
    return DEVICE_COLLECTORS.get(device_type, DEFAULT_DEVICE_COLLECTOR)
