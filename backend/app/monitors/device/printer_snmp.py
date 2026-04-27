"""Define module logic for `backend/app/monitors/device/printer_snmp.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import asyncio
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
)

from ...core.config import printer_snmp_community_for_ip
from ...core.time import utcnow

SNMP_TIMEOUT_SECONDS = 2
SNMP_RETRIES = 1

SYS_UPTIME_OID = "1.3.6.1.2.1.1.3.0"
HR_PRINTER_STATUS_OID = "1.3.6.1.2.1.25.3.5.1.1.1"
HR_PRINTER_ERROR_STATE_OID = "1.3.6.1.2.1.25.3.5.1.2.1"
PRT_INPUT_STATUS_OID = "1.3.6.1.2.1.43.8.2.1.10.1.1"
PRT_MARKER_LIFE_COUNT_OID = "1.3.6.1.2.1.43.10.2.1.4.1.1"
PRT_MARKER_SUPPLIES_LEVEL_BASE_OID = "1.3.6.1.2.1.43.11.1.1.9.1"
PRT_MARKER_SUPPLIES_MAX_BASE_OID = "1.3.6.1.2.1.43.11.1.1.8.1"
PRT_MARKER_COLORANT_BASE_OID = "1.3.6.1.2.1.43.12.1.1.4.1"

COLOR_INDEX_TO_NAME = {
    1: "black",
    2: "cyan",
    3: "magenta",
    4: "yellow",
}

PRINTER_STATUS_LABELS = {
    1: "other",
    2: "unknown",
    3: "idle",
    4: "printing",
    5: "warmup",
}

PAPER_STATUS_LABELS = {
    1: "other",
    2: "unknown",
    3: "available",
    4: "available",
    5: "unavailable",
}

ERROR_STATE_BITS = {
    0: "low_paper",
    1: "no_paper",
    2: "low_toner",
    3: "no_toner",
    4: "door_open",
    5: "jammed",
    6: "offline",
    7: "service_requested",
    8: "input_tray_missing",
    9: "output_tray_missing",
    10: "marker_supply_missing",
    11: "output_near_full",
    12: "output_full",
    13: "input_tray_empty",
    14: "overdue_preventive_maintenance",
}

CRITICAL_ERROR_FLAGS = {
    "no_paper",
    "no_toner",
    "door_open",
    "jammed",
    "offline",
    "service_requested",
    "input_tray_missing",
    "output_tray_missing",
    "marker_supply_missing",
    "output_full",
    "input_tray_empty",
}

WARNING_ERROR_FLAGS = {
    "low_paper",
    "low_toner",
    "output_near_full",
    "overdue_preventive_maintenance",
}


@dataclass(slots=True)
class SnmpPrinterMetric:
    """Perform SnmpPrinterMetric.

    This class encapsulates related behavior and data for this domain area.
    """
    metric_name: str
    metric_value: str
    status: str
    unit: str | None = None


async def collect_printer_snmp_metrics(device_id: int, ip_address: str) -> list[dict]:
    """Collect printer snmp metrics as part of monitoring collection workflows.

    Args:
        device_id: Parameter input untuk routine ini.
        ip_address: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    community = printer_snmp_community_for_ip(ip_address)
    if not community:
        return []

    checked_at = utcnow()
    oids = {
        "printer_uptime_ticks": SYS_UPTIME_OID,
        "printer_status_code": HR_PRINTER_STATUS_OID,
        "printer_error_state_raw": HR_PRINTER_ERROR_STATE_OID,
        "printer_input_status_code": PRT_INPUT_STATUS_OID,
        "printer_total_pages": PRT_MARKER_LIFE_COUNT_OID,
    }
    for color_index, color_name in COLOR_INDEX_TO_NAME.items():
        oids[f"printer_ink_{color_name}_level_raw"] = f"{PRT_MARKER_SUPPLIES_LEVEL_BASE_OID}.{color_index}"
        oids[f"printer_ink_{color_name}_max_raw"] = f"{PRT_MARKER_SUPPLIES_MAX_BASE_OID}.{color_index}"
        oids[f"printer_ink_{color_name}_colorant_raw"] = f"{PRT_MARKER_COLORANT_BASE_OID}.{color_index}"

    raw_values = await _fetch_oid_values(ip_address, community, oids)

    metrics = [
        _build_uptime_metric(raw_values),
        _build_printer_status_metric(raw_values),
        _build_error_state_metric(raw_values),
        _build_ink_status_metric(raw_values),
        _build_paper_status_metric(raw_values),
        _build_total_pages_metric(raw_values),
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
    """Perform fetch oid values.

    Args:
        ip_address: Parameter input untuk routine ini.
        community: Parameter input untuk routine ini.
        oids: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    tasks = {
        key: asyncio.create_task(_snmp_get_value(ip_address, community, oid))
        for key, oid in oids.items()
    }
    return {key: await task for key, task in tasks.items()}


async def _snmp_get_value(ip_address: str, community: str, oid: str) -> object | None:
    """Perform snmp get value.

    Args:
        ip_address: Parameter input untuk routine ini.
        community: Parameter input untuk routine ini.
        oid: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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


def _build_uptime_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build uptime metric.

    Args:
        raw_values: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    uptime_ticks = _safe_int(raw_values.get("printer_uptime_ticks"))
    if uptime_ticks is None:
        return SnmpPrinterMetric("printer_uptime_seconds", "unavailable", "warning")
    return SnmpPrinterMetric("printer_uptime_seconds", str(uptime_ticks // 100), "ok", "s")


def _build_printer_status_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build printer status metric.

    Args:
        raw_values: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    status_code = _safe_int(raw_values.get("printer_status_code"))
    status_label = PRINTER_STATUS_LABELS.get(status_code, "unknown") if status_code is not None else "unknown"
    metric_status = "up" if status_label in {"idle", "printing", "warmup"} else "warning"
    return SnmpPrinterMetric("printer_status", status_label, metric_status)


def _build_error_state_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build error state metric.

    Args:
        raw_values: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    flags = _decode_error_state(raw_values.get("printer_error_state_raw"))
    if not flags:
        return SnmpPrinterMetric("printer_error_state", "none", "ok")
    metric_status = "error" if any(flag in CRITICAL_ERROR_FLAGS for flag in flags) else "warning"
    return SnmpPrinterMetric("printer_error_state", ",".join(flags), metric_status)


def _build_ink_status_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build ink status metric.

    Args:
        raw_values: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    flags = set(_decode_error_state(raw_values.get("printer_error_state_raw")))
    if "no_toner" in flags:
        return SnmpPrinterMetric("printer_ink_status", "empty", "error")
    if "low_toner" in flags:
        return SnmpPrinterMetric("printer_ink_status", "low", "warning")
    return SnmpPrinterMetric("printer_ink_status", "ok", "ok")


def _build_paper_status_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build paper status metric.

    Args:
        raw_values: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    flags = set(_decode_error_state(raw_values.get("printer_error_state_raw")))
    if "no_paper" in flags or "input_tray_empty" in flags:
        return SnmpPrinterMetric("printer_paper_status", "empty", "error")
    if "low_paper" in flags:
        return SnmpPrinterMetric("printer_paper_status", "low", "warning")

    input_status_code = _safe_int(raw_values.get("printer_input_status_code"))
    input_status_label = PAPER_STATUS_LABELS.get(input_status_code, "ok") if input_status_code is not None else "ok"
    metric_status = "ok" if input_status_label in {"available", "ok"} else "warning"
    normalized_label = "ok" if input_status_label == "available" else input_status_label
    return SnmpPrinterMetric("printer_paper_status", normalized_label, metric_status)


def _build_total_pages_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build total pages metric.

    Args:
        raw_values: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    total_pages = _safe_int(raw_values.get("printer_total_pages"))
    if total_pages is None:
        return SnmpPrinterMetric("printer_total_pages", "unavailable", "warning")
    return SnmpPrinterMetric("printer_total_pages", str(total_pages), "ok", "pages")


def _decode_error_state(raw_value: object | None) -> list[str]:
    """Decode error state.

    Args:
        raw_value: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    if raw_value is None:
        return []
    payload = getattr(raw_value, "asOctets", lambda: b"")()
    if not payload:
        return []

    flags: list[str] = []
    for byte_index, byte_value in enumerate(payload):
        for bit_offset in range(8):
            if not (byte_value & (1 << (7 - bit_offset))):
                continue
            bit_index = byte_index * 8 + bit_offset
            flag_name = ERROR_STATE_BITS.get(bit_index)
            if flag_name:
                flags.append(flag_name)
    return flags


def _safe_int(raw_value: object | None) -> int | None:
    """Perform safe int.

    Args:
        raw_value: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    try:
        if raw_value is None:
            return None
        return int(str(raw_value))
    except (TypeError, ValueError):
        return None
