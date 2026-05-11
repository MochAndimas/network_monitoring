"""Synology NAS SNMP collector for priority health metrics."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import cast

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
    next_cmd,
)

from ...core.config import nas_snmp_community_for_ip
from ...core.time import utcnow

SNMP_TIMEOUT_SECONDS = 2
SNMP_RETRIES = 1

SYS_UPTIME_OID = "1.3.6.1.2.1.1.3.0"
SYNO_SYSTEM_STATUS_OID = "1.3.6.1.4.1.6574.1.1.0"
SYNO_SYSTEM_TEMPERATURE_OID = "1.3.6.1.4.1.6574.1.2.0"
SYNO_POWER_STATUS_OID = "1.3.6.1.4.1.6574.1.3.0"
SYNO_SYSTEM_FAN_STATUS_OID = "1.3.6.1.4.1.6574.1.4.1.0"
SYNO_CPU_FAN_STATUS_OID = "1.3.6.1.4.1.6574.1.4.2.0"

SYNO_DISK_TABLE_BASE = "1.3.6.1.4.1.6574.2.1.1"
SYNO_RAID_TABLE_BASE = "1.3.6.1.4.1.6574.3.1.1"
HR_PROCESSOR_TABLE_BASE = "1.3.6.1.2.1.25.3.3.1"
UCD_MEMORY_BASE = "1.3.6.1.4.1.2021.4"

SYNO_STATUS_LABELS = {
    1: "normal",
    2: "failed",
}

SYNO_DISK_STATUS_LABELS = {
    1: "normal",
    2: "initialized",
    3: "not_initialized",
    4: "system_partition_failed",
    5: "crashed",
}

SYNO_RAID_STATUS_LABELS = {
    1: "normal",
    2: "repairing",
    3: "migrating",
    4: "expanding",
    5: "deleting",
    6: "creating",
    7: "syncing",
    8: "parity_checking",
    9: "assembling",
    10: "canceling",
    11: "degraded",
    12: "crashed",
}


@dataclass(slots=True)
class NasMetric:
    """A normalized NAS metric ready for persistence."""

    metric_name: str
    metric_value: str
    status: str
    unit: str | None = None


async def collect_nas_snmp_metrics(device_id: int, ip_address: str) -> list[dict]:
    """Collect Synology NAS SNMP metrics beyond ping reachability."""
    community = nas_snmp_community_for_ip(ip_address)
    if not community:
        return []

    checked_at = utcnow()
    scalar_oids = {
        "nas_uptime_ticks": SYS_UPTIME_OID,
        "nas_system_status_code": SYNO_SYSTEM_STATUS_OID,
        "nas_system_temperature_c": SYNO_SYSTEM_TEMPERATURE_OID,
        "nas_power_status_code": SYNO_POWER_STATUS_OID,
        "nas_system_fan_status_code": SYNO_SYSTEM_FAN_STATUS_OID,
        "nas_cpu_fan_status_code": SYNO_CPU_FAN_STATUS_OID,
    }
    raw_values, disk_rows, raid_rows, processor_loads, memory_values = await asyncio.gather(
        _fetch_oid_values(ip_address, community, scalar_oids),
        _snmp_walk_table(ip_address, community, SYNO_DISK_TABLE_BASE),
        _snmp_walk_table(ip_address, community, SYNO_RAID_TABLE_BASE),
        _snmp_walk_table(ip_address, community, HR_PROCESSOR_TABLE_BASE),
        _snmp_walk_table(ip_address, community, UCD_MEMORY_BASE),
    )

    metrics = [
        _build_uptime_metric(raw_values),
        _build_cpu_metric(processor_loads),
        _build_memory_metric(memory_values),
        _build_system_status_metric(raw_values),
        _build_power_status_metric(raw_values),
        _build_system_temperature_metric(raw_values),
        _build_fan_status_metric("system", raw_values.get("nas_system_fan_status_code")),
        _build_fan_status_metric("cpu", raw_values.get("nas_cpu_fan_status_code")),
        *_build_volume_and_raid_metrics(raid_rows),
        *_build_disk_metrics(disk_rows),
    ]

    return [
        {
            "device_id": device_id,
            "metric_name": metric.metric_name,
            "metric_value": metric.metric_value,
            "status": metric.status,
            "unit": metric.unit,
            "checked_at": checked_at,
        }
        for metric in metrics
    ]


async def _fetch_oid_values(ip_address: str, community: str, oids: dict[str, str]) -> dict[str, object | None]:
    tasks = {key: asyncio.create_task(_snmp_get_value(ip_address, community, oid)) for key, oid in oids.items()}
    return {key: await task for key, task in tasks.items()}


async def _snmp_get_value(ip_address: str, community: str, oid: str) -> object | None:
    engine = SnmpEngine()
    try:
        error_indication, error_status, _, var_binds = await get_cmd(
            engine,
            CommunityData(community, mpModel=1),
            await UdpTransportTarget.create((ip_address, 161), timeout=SNMP_TIMEOUT_SECONDS, retries=SNMP_RETRIES),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication or error_status or not var_binds:
            return None
        return cast(object, var_binds[0][1])
    except Exception:
        return None
    finally:
        try:
            engine.transport_dispatcher.close_dispatcher()
        except Exception:
            pass


async def _snmp_walk_table(ip_address: str, community: str, base_oid: str) -> dict[int, dict[int, str]]:
    engine = SnmpEngine()
    rows: dict[int, dict[int, str]] = {}
    base_tuple = _oid_tuple(base_oid)
    current_oid = base_oid
    try:
        transport = await UdpTransportTarget.create((ip_address, 161), timeout=SNMP_TIMEOUT_SECONDS, retries=SNMP_RETRIES)
        while True:
            error_indication, error_status, _, var_binds = await next_cmd(
                engine,
                CommunityData(community, mpModel=1),
                transport,
                ContextData(),
                ObjectType(ObjectIdentity(current_oid)),
                lexicographicMode=True,
            )
            if error_indication or error_status or not var_binds:
                break
            name, value = var_binds[0]
            oid_parts = name.asTuple()
            if oid_parts[: len(base_tuple)] != base_tuple or len(oid_parts) < len(base_tuple) + 2:
                break
            column = int(oid_parts[len(base_tuple)])
            index = int(oid_parts[-1])
            rows.setdefault(index, {})[column] = value.prettyPrint()
            current_oid = ".".join(str(part) for part in oid_parts)
    except Exception:
        return rows
    finally:
        try:
            engine.transport_dispatcher.close_dispatcher()
        except Exception:
            pass
    return rows


def _build_uptime_metric(raw_values: dict[str, object | None]) -> NasMetric:
    uptime_ticks = _safe_int(raw_values.get("nas_uptime_ticks"))
    if uptime_ticks is None:
        return NasMetric("nas_uptime_seconds", "unavailable", "warning")
    return NasMetric("nas_uptime_seconds", str(uptime_ticks // 100), "ok", "s")


def _build_cpu_metric(processor_loads: dict[int, dict[int, str]]) -> NasMetric:
    values = [_safe_float(row.get(2)) for row in processor_loads.values()]
    values = [value for value in values if value is not None]
    if not values:
        return NasMetric("cpu_percent", "unavailable", "warning", "%")
    return NasMetric("cpu_percent", f"{sum(values) / len(values):.2f}", "ok", "%")


def _build_memory_metric(memory_values: dict[int, dict[int, str]]) -> NasMetric:
    values = {
        column: _safe_float(raw_value)
        for row in memory_values.values()
        for column, raw_value in row.items()
    }
    total_real = values.get(5)
    free_real = values.get(6) or 0.0
    buffered = values.get(14) or 0.0
    cached = values.get(15) or 0.0
    if not total_real:
        return NasMetric("memory_percent", "unavailable", "warning", "%")
    used_percent = max(((total_real - free_real - buffered - cached) / total_real) * 100, 0.0)
    return NasMetric("memory_percent", f"{used_percent:.2f}", "ok", "%")


def _build_system_status_metric(raw_values: dict[str, object | None]) -> NasMetric:
    label = _syno_status_label(raw_values.get("nas_system_status_code"))
    return NasMetric("nas_system_status", label, _status_for_normal_label(label))


def _build_power_status_metric(raw_values: dict[str, object | None]) -> NasMetric:
    label = _syno_status_label(raw_values.get("nas_power_status_code"))
    return NasMetric("nas_power_status", label, _status_for_normal_label(label))


def _build_system_temperature_metric(raw_values: dict[str, object | None]) -> NasMetric:
    value = _safe_float(raw_values.get("nas_system_temperature_c"))
    if value is None:
        return NasMetric("nas_system_temperature_c", "unavailable", "warning", "C")
    return NasMetric("nas_system_temperature_c", f"{value:.2f}", "ok", "C")


def _build_fan_status_metric(name: str, raw_value: object | None) -> NasMetric:
    label = _syno_status_label(raw_value)
    return NasMetric(f"nas_fan:{name}:status", label, _status_for_normal_label(label))


def _build_volume_and_raid_metrics(rows: dict[int, dict[int, str]]) -> list[NasMetric]:
    metrics: list[NasMetric] = []
    disk_percent_values: list[float] = []
    for row in rows.values():
        name = str(row.get(2) or "").strip()
        if not name:
            continue
        slug = _slug(name)
        status_label = _raid_status_label(row.get(3))
        free_bytes = _safe_float(row.get(4))
        total_bytes = _safe_float(row.get(5))
        if name.lower().startswith("volume"):
            metrics.append(NasMetric(f"nas_volume:{slug}:status", status_label, _status_for_raid_label(status_label)))
            if total_bytes:
                used_bytes = max(total_bytes - (free_bytes or 0.0), 0.0)
                used_percent = max((used_bytes / total_bytes) * 100, 0.0)
                disk_percent_values.append(used_percent)
                metrics.append(NasMetric(f"nas_volume:{slug}:total_bytes", f"{total_bytes:.0f}", "ok", "bytes"))
                metrics.append(NasMetric(f"nas_volume:{slug}:used_bytes", f"{used_bytes:.0f}", "ok", "bytes"))
                metrics.append(NasMetric(f"nas_volume:{slug}:free_bytes", f"{free_bytes or 0.0:.0f}", "ok", "bytes"))
                metrics.append(NasMetric(f"nas_volume:{slug}:used_percent", f"{used_percent:.2f}", "ok", "%"))
        else:
            metrics.append(NasMetric(f"nas_raid:{slug}:status", status_label, _status_for_raid_label(status_label)))
    if disk_percent_values:
        metrics.append(NasMetric("disk_percent", f"{max(disk_percent_values):.2f}", "ok", "%"))
    return metrics


def _build_disk_metrics(rows: dict[int, dict[int, str]]) -> list[NasMetric]:
    metrics: list[NasMetric] = []
    for row in rows.values():
        name = str(row.get(12) or row.get(2) or "").strip()
        if not name:
            continue
        slug = _slug(name)
        status_label = _disk_status_label(row.get(5))
        temperature = _safe_float(row.get(6))
        metrics.append(NasMetric(f"nas_disk:{slug}:status", status_label, _status_for_disk_label(status_label)))
        if temperature is not None:
            metrics.append(NasMetric(f"nas_disk:{slug}:temperature_c", f"{temperature:.2f}", "ok", "C"))
    return metrics


def _syno_status_label(raw_value: object | None) -> str:
    return SYNO_STATUS_LABELS.get(_safe_int(raw_value) or 0, "unknown")


def _disk_status_label(raw_value: object | None) -> str:
    return SYNO_DISK_STATUS_LABELS.get(_safe_int(raw_value) or 0, "unknown")


def _raid_status_label(raw_value: object | None) -> str:
    return SYNO_RAID_STATUS_LABELS.get(_safe_int(raw_value) or 0, "unknown")


def _status_for_normal_label(label: str) -> str:
    return "ok" if label == "normal" else "error" if label == "failed" else "warning"


def _status_for_disk_label(label: str) -> str:
    if label in {"normal", "initialized"}:
        return "ok"
    return "error" if label in {"crashed", "system_partition_failed"} else "warning"


def _status_for_raid_label(label: str) -> str:
    if label == "normal":
        return "ok"
    if label in {"degraded", "crashed"}:
        return "error"
    return "warning"


def _safe_int(raw_value: object | None) -> int | None:
    try:
        if raw_value is None:
            return None
        return int(str(raw_value))
    except (TypeError, ValueError):
        return None


def _safe_float(raw_value: object | None) -> float | None:
    try:
        if raw_value is None:
            return None
        return float(str(raw_value))
    except (TypeError, ValueError):
        return None


def _oid_tuple(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split(".") if part)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "unknown"
