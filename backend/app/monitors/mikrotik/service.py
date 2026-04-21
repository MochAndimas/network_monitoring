from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...models.metric import Metric
from ...repositories.device_repository import DeviceRepository
from ...repositories.metric_repository import MetricRepository
from ...services.monitoring_service import utcnow
from ..helpers import bounded_gather, build_ping_metric, build_ping_quality_metrics, collect_ping_samples, latest_successful_ping

try:
    from librouteros import connect
except ImportError:  # pragma: no cover - dependency is declared but kept defensive
    connect = None


logger = logging.getLogger("network_monitoring.mikrotik")

MAX_DYNAMIC_METRIC_NAME_LENGTH = 100
FIREWALL_SPIKE_PPS_WARNING = 1000.0
FIREWALL_SPIKE_MBPS_WARNING = 50.0


async def run_mikrotik_checks(db: AsyncSession) -> list[dict]:
    devices = await _list_mikrotik_devices(db)
    metrics: list[dict] = [
        metric
        for device_metrics in await bounded_gather(
            [_build_ping_metrics(device.id, device.ip_address) for device in devices if _should_collect_ping(device)]
        )
        for metric in device_metrics
    ]

    if not devices or not settings.mikrotik_host or connect is None:
        return metrics

    api = None
    try:
        api = await asyncio.to_thread(
            connect,
            host=settings.mikrotik_host,
            port=settings.mikrotik_port,
            username=settings.mikrotik_username,
            password=settings.mikrotik_password,
        )
        resources = await asyncio.to_thread(lambda: list(api.path("system", "resource")))
        interfaces = await asyncio.to_thread(lambda: list(api.path("interface")))
        dhcp_leases = await asyncio.to_thread(lambda: list(api.path("ip", "dhcp-server", "lease")))
        arp_entries = await asyncio.to_thread(lambda: list(api.path("ip", "arp")))
        firewall_filters = await asyncio.to_thread(lambda: list(api.path("ip", "firewall", "filter")))
        firewall_nat = await asyncio.to_thread(lambda: list(api.path("ip", "firewall", "nat")))
        simple_queues = await asyncio.to_thread(lambda: list(api.path("queue", "simple")))
        resource = resources[0] if resources else {}
        checked_at = utcnow()
        target_device = devices[0]
        previous_metrics = await _latest_metric_map(db, target_device.id)

        metrics.extend(
            [
                {
                    "device_id": target_device.id,
                    "metric_name": "mikrotik_api",
                    "metric_value": "ok",
                    "status": "ok",
                    "unit": None,
                    "checked_at": checked_at,
                },
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
                    "metric_name": "memory_used_bytes",
                    "metric_value": str(_memory_used_bytes(resource)),
                    "status": "ok",
                    "unit": "bytes",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "memory_free_bytes",
                    "metric_value": str(_safe_int(resource.get("free-memory"))),
                    "status": "ok",
                    "unit": "bytes",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "disk_percent",
                    "metric_value": _mikrotik_disk_percent(resource),
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "disk_used_bytes",
                    "metric_value": str(_disk_used_bytes(resource)),
                    "status": "ok",
                    "unit": "bytes",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "disk_free_bytes",
                    "metric_value": str(_safe_int(resource.get("free-hdd-space"))),
                    "status": "ok",
                    "unit": "bytes",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "interfaces_running",
                    "metric_value": str(sum(1 for item in interfaces if _truthy(item.get("running")))),
                    "status": "ok",
                    "unit": "count",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "dhcp_active_leases",
                    "metric_value": str(_active_dhcp_lease_count(dhcp_leases)),
                    "status": "ok",
                    "unit": "count",
                    "checked_at": checked_at,
                },
                {
                    "device_id": target_device.id,
                    "metric_name": "connected_clients",
                    "metric_value": str(_connected_client_count(dhcp_leases, arp_entries)),
                    "status": "ok",
                    "unit": "count",
                    "checked_at": checked_at,
                },
            ]
        )
        metrics.extend(_interface_metrics(target_device.id, interfaces, previous_metrics, checked_at))
        metrics.extend(_firewall_metrics(target_device.id, "filter", firewall_filters, previous_metrics, checked_at))
        metrics.extend(_firewall_metrics(target_device.id, "nat", firewall_nat, previous_metrics, checked_at))
        metrics.extend(_queue_metrics(target_device.id, simple_queues, previous_metrics, checked_at))
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


async def _list_mikrotik_devices(db: AsyncSession) -> list:
    devices = await DeviceRepository(db).list_devices(active_only=True)
    return [
        device
        for device in devices
        if str(device.device_type or "").lower() == "mikrotik" or "mikrotik" in str(device.name or "").lower()
    ]


def _should_collect_ping(device) -> bool:
    return str(device.device_type or "").lower() == "mikrotik"


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


async def _latest_metric_map(db: AsyncSession, device_id: int) -> dict[str, Metric]:
    repository = MetricRepository(db)
    metrics = await repository.list_recent_metrics(limit=5000, device_id=device_id)
    latest: dict[str, Metric] = {}
    for metric in metrics:
        latest.setdefault(metric.metric_name, metric)
    return latest


def _interface_metrics(device_id: int, interfaces: list[dict], previous_metrics: dict[str, Metric], checked_at: datetime) -> list[dict]:
    metrics: list[dict] = []
    for interface in interfaces:
        if _truthy(interface.get("disabled")):
            continue
        name = _object_name(interface, fallback_prefix="interface")
        prefix = _dynamic_metric_name("interface", name)
        rx_bytes = _safe_int(interface.get("rx-byte") or interface.get("rx-bytes"))
        tx_bytes = _safe_int(interface.get("tx-byte") or interface.get("tx-bytes"))
        running = _truthy(interface.get("running"))
        status = "up" if running else "ok"
        metrics.extend(
            [
                _metric(device_id, f"{prefix}:rx_bytes", rx_bytes, status, "bytes", checked_at),
                _metric(device_id, f"{prefix}:tx_bytes", tx_bytes, status, "bytes", checked_at),
                _metric(
                    device_id,
                    f"{prefix}:rx_mbps",
                    _counter_rate(rx_bytes, previous_metrics.get(f"{prefix}:rx_bytes"), checked_at),
                    status,
                    "Mbps",
                    checked_at,
                ),
                _metric(
                    device_id,
                    f"{prefix}:tx_mbps",
                    _counter_rate(tx_bytes, previous_metrics.get(f"{prefix}:tx_bytes"), checked_at),
                    status,
                    "Mbps",
                    checked_at,
                ),
            ]
        )
    return metrics


def _firewall_metrics(
    device_id: int,
    section: str,
    rules: list[dict],
    previous_metrics: dict[str, Metric],
    checked_at: datetime,
) -> list[dict]:
    metrics: list[dict] = []
    for index, rule in enumerate(rules, start=1):
        if _truthy(rule.get("disabled")):
            continue
        name = _firewall_rule_name(rule, index)
        prefix = _dynamic_metric_name("firewall", section, name)
        packets = _safe_int(rule.get("packets"))
        bytes_count = _safe_int(rule.get("bytes"))
        packets_per_second = _counter_per_second(packets, previous_metrics.get(f"{prefix}:packets"), checked_at)
        mbps = _counter_rate(bytes_count, previous_metrics.get(f"{prefix}:bytes"), checked_at)
        spike_status = (
            "warning"
            if packets_per_second >= FIREWALL_SPIKE_PPS_WARNING or mbps >= FIREWALL_SPIKE_MBPS_WARNING
            else "ok"
        )
        metrics.extend(
            [
                _metric(device_id, f"{prefix}:packets", packets, "ok", "packets", checked_at),
                _metric(device_id, f"{prefix}:bytes", bytes_count, "ok", "bytes", checked_at),
                _metric(device_id, f"{prefix}:pps", packets_per_second, spike_status, "pps", checked_at),
                _metric(device_id, f"{prefix}:mbps", mbps, spike_status, "Mbps", checked_at),
            ]
        )
    return metrics


def _queue_metrics(device_id: int, queues: list[dict], previous_metrics: dict[str, Metric], checked_at: datetime) -> list[dict]:
    metrics: list[dict] = []
    for queue in queues:
        if _truthy(queue.get("disabled")):
            continue
        name = _object_name(queue, fallback_prefix="queue")
        prefix = _dynamic_metric_name("queue", name)
        rx_bytes, tx_bytes = _split_counter_pair(queue.get("bytes"))
        rx_rate, tx_rate = _split_counter_pair(queue.get("rate"))
        rx_mbps = _bits_to_mbps(rx_rate) if rx_rate else _counter_rate(rx_bytes, previous_metrics.get(f"{prefix}:rx_bytes"), checked_at)
        tx_mbps = _bits_to_mbps(tx_rate) if tx_rate else _counter_rate(tx_bytes, previous_metrics.get(f"{prefix}:tx_bytes"), checked_at)
        metrics.extend(
            [
                _metric(device_id, f"{prefix}:rx_bytes", rx_bytes, "ok", "bytes", checked_at),
                _metric(device_id, f"{prefix}:tx_bytes", tx_bytes, "ok", "bytes", checked_at),
                _metric(device_id, f"{prefix}:rx_mbps", rx_mbps, "ok", "Mbps", checked_at),
                _metric(device_id, f"{prefix}:tx_mbps", tx_mbps, "ok", "Mbps", checked_at),
            ]
        )
    return metrics


def _metric(device_id: int, metric_name: str, value: int | float | str, status: str, unit: str | None, checked_at: datetime) -> dict:
    if isinstance(value, float):
        metric_value = f"{value:.2f}"
    else:
        metric_value = str(value)
    return {
        "device_id": device_id,
        "metric_name": metric_name[:MAX_DYNAMIC_METRIC_NAME_LENGTH],
        "metric_value": metric_value,
        "status": status,
        "unit": unit,
        "checked_at": checked_at,
    }


def _mikrotik_disk_percent(resource: dict) -> str:
    total = _safe_int(resource.get("total-hdd-space"))
    free = _safe_int(resource.get("free-hdd-space"))
    if total <= 0:
        return "0"
    return f"{((total - free) / total) * 100:.2f}"


def _memory_used_bytes(resource: dict) -> int:
    return max(_safe_int(resource.get("total-memory")) - _safe_int(resource.get("free-memory")), 0)


def _disk_used_bytes(resource: dict) -> int:
    return max(_safe_int(resource.get("total-hdd-space")) - _safe_int(resource.get("free-hdd-space")), 0)


def _active_dhcp_lease_count(leases: list[dict]) -> int:
    return sum(1 for lease in leases if _is_active_dhcp_lease(lease))


def _connected_client_count(leases: list[dict], arp_entries: list[dict]) -> int:
    mac_addresses = {
        str(lease.get("mac-address") or "").strip().lower()
        for lease in leases
        if _is_active_dhcp_lease(lease) and str(lease.get("mac-address") or "").strip()
    }
    mac_addresses.update(
        str(entry.get("mac-address") or "").strip().lower()
        for entry in arp_entries
        if str(entry.get("mac-address") or "").strip() and not _truthy(entry.get("disabled"))
    )
    return len(mac_addresses)


def _is_active_dhcp_lease(lease: dict) -> bool:
    status = str(lease.get("status") or "").strip().lower()
    return status == "bound" or bool(str(lease.get("active-address") or "").strip())


def _counter_rate(current_value: int, previous_metric: Metric | None, checked_at: datetime) -> float:
    return (_counter_per_second(current_value, previous_metric, checked_at) * 8) / 1_000_000


def _counter_per_second(current_value: int, previous_metric: Metric | None, checked_at: datetime) -> float:
    if previous_metric is None:
        return 0.0
    previous_value = _safe_int(previous_metric.metric_value)
    elapsed_seconds = max((checked_at - previous_metric.checked_at).total_seconds(), 0)
    if elapsed_seconds <= 0 or current_value < previous_value:
        return 0.0
    return (current_value - previous_value) / elapsed_seconds


def _split_counter_pair(raw_value) -> tuple[int, int]:
    if raw_value is None:
        return 0, 0
    if isinstance(raw_value, (tuple, list)) and len(raw_value) >= 2:
        return _safe_int(raw_value[0]), _safe_int(raw_value[1])
    parts = re.split(r"[/,; ]+", str(raw_value).strip())
    numbers = [_safe_int(part) for part in parts if part != ""]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return numbers[0], 0
    return 0, 0


def _bits_to_mbps(bits_per_second: int) -> float:
    return bits_per_second / 1_000_000


def _firewall_rule_name(rule: dict, index: int) -> str:
    chain = str(rule.get("chain") or "rule").strip()
    action = str(rule.get("action") or "").strip()
    comment = str(rule.get("comment") or "").strip()
    raw_name = "_".join(item for item in [f"{index:03d}", chain, action, comment] if item)
    return raw_name or f"rule_{index:03d}"


def _object_name(item: dict, *, fallback_prefix: str) -> str:
    return str(item.get("name") or item.get("comment") or item.get(".id") or fallback_prefix).strip()


def _dynamic_metric_name(*parts: str) -> str:
    normalized_parts = [_slugify(part) for part in parts if str(part or "").strip()]
    metric_name = ":".join(normalized_parts)
    if len(metric_name) <= MAX_DYNAMIC_METRIC_NAME_LENGTH - 12:
        return metric_name
    head = ":".join(normalized_parts[:-1])
    tail = normalized_parts[-1][: max(MAX_DYNAMIC_METRIC_NAME_LENGTH - len(head) - 13, 8)]
    return f"{head}:{tail}".strip(":")


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value).strip().lower()).strip("_")
    return normalized or "unknown"


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "yes", "1", "enabled", "running"}


def _safe_int(value) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
