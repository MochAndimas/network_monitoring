"""Monitoring collector helpers for printer snmp."""

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
from ..contracts import classify_snmp_error, collection_metric_status, normalize_collection_status
from ..helpers import retry_transient_collection, vendor_protocol_guard

SNMP_TIMEOUT_SECONDS = 2
SNMP_RETRIES = 1
SNMP_MAX_CONCURRENT_REQUESTS = 4

SYS_UPTIME_OID = "1.3.6.1.2.1.1.3.0"
HR_PRINTER_STATUS_OID = "1.3.6.1.2.1.25.3.5.1.1.1"
HR_PRINTER_ERROR_STATE_OID = "1.3.6.1.2.1.25.3.5.1.2.1"
PRT_INPUT_STATUS_OID = "1.3.6.1.2.1.43.8.2.1.10.1.1"
PRT_INPUT_MAX_CAPACITY_OID = "1.3.6.1.2.1.43.8.2.1.9.1.1"
PRT_INPUT_NAME_OID = "1.3.6.1.2.1.43.8.2.1.13.1.1"
PRT_MARKER_LIFE_COUNT_OID = "1.3.6.1.2.1.43.10.2.1.4.1.1"
PRT_MARKER_SUPPLIES_LEVEL_BASE_OID = "1.3.6.1.2.1.43.11.1.1.9.1"
PRT_MARKER_COLORANT_BASE_OID = "1.3.6.1.2.1.43.12.1.1.4.1"

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
    """Helper object for device inventory and status."""
    metric_name: str
    metric_value: str
    status: str
    unit: str | None = None


@dataclass(slots=True)
class SnmpReadResult:
    """One SNMP read with a credential-safe operational outcome category."""

    value: object | None
    error_category: str | None = None


@dataclass(slots=True)
class SnmpFetchResult:
    """Printer SNMP values plus collector health metadata."""

    values: dict[str, object | None]
    collection_status: str
    protocol: str


async def collect_printer_snmp_metrics(device_id: int, ip_address: str) -> list[dict]:
    """Collect printer snmp metrics for monitoring collection."""
    community = printer_snmp_community_for_ip(ip_address)
    checked_at = utcnow()
    if not community:
        return [_metric_payload(device_id, SnmpPrinterMetric("printer_snmp_collection_status", "configuration_missing", "warning"), checked_at)]
    oids = {
        "printer_uptime_ticks": SYS_UPTIME_OID,
        "printer_status_code": HR_PRINTER_STATUS_OID,
        "printer_error_state_raw": HR_PRINTER_ERROR_STATE_OID,
        "printer_input_status_code": PRT_INPUT_STATUS_OID,
        "printer_input_max_capacity": PRT_INPUT_MAX_CAPACITY_OID,
        "printer_input_name": PRT_INPUT_NAME_OID,
        "printer_total_pages": PRT_MARKER_LIFE_COUNT_OID,
    }
    # Query only the black supply. It is enough for monochrome printers such
    # as the Canon iR-ADV 4551 and avoids overloading legacy SNMPv1 agents
    # with unsupported CMYK supply OIDs.
    oids["printer_ink_black_level_raw"] = f"{PRT_MARKER_SUPPLIES_LEVEL_BASE_OID}.1"
    oids["printer_ink_black_colorant_raw"] = f"{PRT_MARKER_COLORANT_BASE_OID}.1"

    async with vendor_protocol_guard("printer-snmp"):
        fetch_result = await retry_transient_collection(
            lambda: _fetch_oid_values(ip_address, community, oids),
            retryable_statuses={"timeout", "connection_failed", "collector_error"},
        )
    raw_values = fetch_result.values

    metrics = [
        SnmpPrinterMetric(
            "printer_snmp_collection_status",
            fetch_result.collection_status,
            collection_metric_status(fetch_result.collection_status),
            fetch_result.protocol,
        ),
        _build_uptime_metric(raw_values),
        _build_printer_status_metric(raw_values),
        _build_error_state_metric(raw_values),
        _build_ink_status_metric(raw_values),
        _build_black_toner_metric(raw_values),
        _build_paper_status_metric(raw_values),
        _build_paper_detail_metric(raw_values),
        _build_total_pages_metric(raw_values),
    ]

    return [_metric_payload(device_id, metric, checked_at) for metric in metrics]


def _metric_payload(device_id: int, metric: SnmpPrinterMetric, checked_at) -> dict:
    """Convert a normalized printer metric to the common persistence payload."""
    return {
        "device_id": device_id,
        "metric_name": metric.metric_name,
        "metric_value": metric.metric_value,
        "status": metric.status,
        "unit": metric.unit,
        "checked_at": checked_at,
    }


async def _fetch_oid_values(ip_address: str, community: str, oids: dict[str, str]) -> SnmpFetchResult:
    """Fetch OID values, preferring SNMPv1 for legacy printer fleets."""
    # Canon imageRUNNER devices commonly expose v1 only. Starting with v1
    # avoids an initial burst of v2c timeouts before every collection cycle.
    first_result = await _fetch_oid_values_for_version(ip_address, community, oids, mp_model=0)
    # sysUpTime is a required, stable scalar for every supported printer.  Some
    # devices return no-such placeholders for optional OIDs over the wrong SNMP
    # version, so an arbitrary non-empty response is not enough to select v2c.
    if _safe_int(first_result.values.get("printer_uptime_ticks")) is not None:
        return first_result
    return await _fetch_oid_values_for_version(ip_address, community, oids, mp_model=1)


async def _fetch_oid_values_for_version(
    ip_address: str,
    community: str,
    oids: dict[str, str],
    *,
    mp_model: int,
) -> SnmpFetchResult:
    """Fetch all printer OIDs concurrently for one SNMP protocol version."""
    semaphore = asyncio.Semaphore(SNMP_MAX_CONCURRENT_REQUESTS)

    async def _read_one(oid: str) -> SnmpReadResult:
        async with semaphore:
            return await _snmp_get_value(ip_address, community, oid, mp_model=mp_model)

    tasks = {key: asyncio.create_task(_read_one(oid)) for key, oid in oids.items()}
    results = {key: await task for key, task in tasks.items()}
    uptime_result = results["printer_uptime_ticks"]
    return SnmpFetchResult(
        values={key: result.value for key, result in results.items()},
        collection_status="ok" if _safe_int(uptime_result.value) is not None else normalize_collection_status(uptime_result.error_category, fallback="invalid_response"),
        protocol=f"snmpv{1 if mp_model == 0 else '2c'}",
    )


async def _snmp_get_value(ip_address: str, community: str, oid: str, *, mp_model: int) -> SnmpReadResult:
    """Run snmp get value for device inventory and status."""
    engine = SnmpEngine()
    try:
        error_indication, error_status, _, var_binds = await get_cmd(
            engine,
            CommunityData(community, mpModel=mp_model),
            await UdpTransportTarget.create((ip_address, 161), timeout=SNMP_TIMEOUT_SECONDS, retries=SNMP_RETRIES),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication:
            return SnmpReadResult(None, _snmp_error_category(str(error_indication)))
        if error_status:
            return SnmpReadResult(None, "protocol_error")
        if not var_binds:
            return SnmpReadResult(None, "invalid_response")
        return SnmpReadResult(cast(object, var_binds[0][1]))
    except TimeoutError:
        return SnmpReadResult(None, "timeout")
    except Exception:
        return SnmpReadResult(None, "collector_error")
    finally:
        try:
            engine.transport_dispatcher.close_dispatcher()
        except Exception:
            pass


def _snmp_error_category(error_message: str) -> str:
    """Map pysnmp transport text to a stable credential-safe category."""
    return classify_snmp_error(error_message)


def _build_uptime_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build uptime metric for monitoring collection."""
    uptime_ticks = _safe_int(raw_values.get("printer_uptime_ticks"))
    if uptime_ticks is None:
        return SnmpPrinterMetric("printer_uptime_seconds", "unavailable", "warning")
    return SnmpPrinterMetric("printer_uptime_seconds", str(uptime_ticks // 100), "ok", "s")


def _build_printer_status_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build printer status metric for monitoring collection."""
    status_code = _safe_int(raw_values.get("printer_status_code"))
    status_label = PRINTER_STATUS_LABELS.get(status_code, "unknown") if status_code is not None else "unknown"
    metric_status = "up" if status_label in {"idle", "printing", "warmup"} else "warning"
    return SnmpPrinterMetric("printer_status", status_label, metric_status)


def _build_error_state_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build error state metric for monitoring collection."""
    flags = _decode_error_state(raw_values.get("printer_error_state_raw"))
    if not flags:
        return SnmpPrinterMetric("printer_error_state", "none", "ok")
    metric_status = "error" if any(flag in CRITICAL_ERROR_FLAGS for flag in flags) else "warning"
    return SnmpPrinterMetric("printer_error_state", ",".join(flags), metric_status)


def _build_ink_status_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build ink status metric for monitoring collection."""
    flags = set(_decode_error_state(raw_values.get("printer_error_state_raw")))
    if "no_toner" in flags:
        return SnmpPrinterMetric("printer_ink_status", "empty", "error")
    if "low_toner" in flags:
        return SnmpPrinterMetric("printer_ink_status", "low", "warning")
    return SnmpPrinterMetric("printer_ink_status", "ok", "ok")


def _build_black_toner_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build an optional black-toner percentage from the standard Printer MIB."""
    toner_level = _safe_int(raw_values.get("printer_ink_black_level_raw"))
    colorant = str(raw_values.get("printer_ink_black_colorant_raw") or "").strip().lower()
    if toner_level is None or colorant not in {"", "black"} or not 0 <= toner_level <= 100:
        return SnmpPrinterMetric("printer_toner_black_percent", "unavailable", "warning", "%")
    if toner_level <= 5:
        status = "error"
    elif toner_level <= 20:
        status = "warning"
    else:
        status = "ok"
    return SnmpPrinterMetric("printer_toner_black_percent", str(toner_level), status, "%")


def _build_paper_status_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build paper status metric for monitoring collection."""
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


def _build_paper_detail_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build a human-readable explanation of the input tray that needs attention."""
    tray_name = str(raw_values.get("printer_input_name") or "Input tray").strip() or "Input tray"
    current_level = _safe_int(raw_values.get("printer_input_status_code"))
    max_capacity = _safe_int(raw_values.get("printer_input_max_capacity"))
    if current_level is None:
        return SnmpPrinterMetric("printer_paper_detail", "unavailable", "warning")
    if max_capacity and max_capacity > 0:
        level_description = f"{current_level}/{max_capacity} lembar"
    else:
        level_description = f"{current_level} lembar"
    if current_level <= 0:
        condition = "kosong"
    elif max_capacity and current_level / max_capacity <= 0.2:
        condition = "menipis"
    else:
        condition = "tersedia"
    status = "warning" if condition in {"kosong", "menipis"} else "ok"
    return SnmpPrinterMetric("printer_paper_detail", f"{tray_name}: {condition} ({level_description})", status)


def _build_total_pages_metric(raw_values: dict[str, object | None]) -> SnmpPrinterMetric:
    """Build total pages metric for monitoring collection."""
    total_pages = _safe_int(raw_values.get("printer_total_pages"))
    if total_pages is None:
        return SnmpPrinterMetric("printer_total_pages", "unavailable", "warning")
    return SnmpPrinterMetric("printer_total_pages", str(total_pages), "ok", "pages")


def _decode_error_state(raw_value: object | None) -> list[str]:
    """Decode error state for monitoring collection."""
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
    """Safely return safe int for device inventory and status."""
    try:
        if raw_value is None:
            return None
        return int(str(raw_value))
    except (TypeError, ValueError):
        return None
