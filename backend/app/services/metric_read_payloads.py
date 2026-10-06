"""Metric read payloads: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import datetime

from ..api.schemas import DeviceMonitoringContext, MetricHistoryItem, MetricHistorySection, MetricPayloadMeta
from .observability_service import record_api_payload_request, record_api_payload_section


def metric_history_dicts(metrics: list[dict]) -> list[dict]:
    """Convert repository metric rows into API response dictionaries."""
    return [
        {
            "id": metric["id"],
            "device_id": metric["device_id"],
            "device_name": metric["device_name"],
            "metric_name": metric["metric_name"],
            "metric_value": metric["metric_value"],
            "metric_value_numeric": metric["metric_value_numeric"],
            "status": metric["status"],
            "unit": metric["unit"],
            "checked_at": metric["checked_at"],
        }
        for metric in metrics
    ]


def metric_history_items(metrics: list[dict]) -> list[MetricHistoryItem]:
    """Convert repository metric rows into typed MetricHistoryItem objects."""
    return [MetricHistoryItem(**metric) for metric in metric_history_dicts(metrics)]


def _device_monitoring_context(items: list[dict]) -> DeviceMonitoringContext:
    """Build safe per-device capability and freshness context from latest metrics."""
    if not items:
        return DeviceMonitoringContext(
            state="unavailable",
            reason="Tidak ada snapshot metric untuk device ini. Periksa collector, konektivitas, dan konfigurasi perangkat.",
            capabilities=[],
        )
    statuses = {str(item.get("status") or "unknown").lower() for item in items}
    state = "degraded" if statuses & {"down", "error", "warning", "stale"} else "healthy"
    latest = max(
        (checked_at for item in items if isinstance(checked_at := item.get("checked_at"), datetime)),
        default=None,
    )
    reason = (
        "Metric terakhir mengindikasikan monitoring degraded; periksa collector/freshness sebelum menyimpulkan perangkat gagal."
        if state == "degraded"
        else "Snapshot metric tersedia dari collector."
    )
    return DeviceMonitoringContext(
        state=state,
        reason=reason,
        capabilities=sorted({str(item.get("metric_name")) for item in items}),
        latest_checked_at=latest,
    )


def _history_section(
    items: list[dict],
    *,
    total: int,
    limit: int,
    offset: int,
    sampled: bool | None = None,
) -> MetricHistorySection:
    """Build a typed composite metric payload section."""
    return MetricHistorySection(
        items=[MetricHistoryItem(**item) for item in items],
        meta=MetricPayloadMeta(total=total, limit=limit, offset=offset, sampled=sampled),
    )


def _record_payload_section(
    *,
    endpoint: str,
    device_id: int | None,
    section: str,
    rows: int,
    total_rows: int | None,
    sampled: bool,
) -> None:
    """Record observability counters for one metric API payload section."""
    payload_scope = "device" if device_id is not None else "global"
    record_api_payload_request(endpoint=endpoint, scope=payload_scope)
    record_api_payload_section(
        endpoint=endpoint,
        scope=payload_scope,
        section=section,
        rows=rows,
        total_rows=total_rows,
        sampled=sampled,
    )


def _record_context_payload_sections(
    *,
    endpoint: str,
    device_id: int | None,
    history_items: list[dict],
    history_total: int,
    selected_device_history_items: list[dict],
    selected_device_history_total: int,
    selected_device_trend_items: list[dict],
    selected_device_trend_total: int,
    latest_snapshot_items: list[dict],
    latest_snapshot_total: int,
    selected_device_snapshot_items: list[dict],
    selected_device_snapshot_total: int,
    force_sampled: bool = False,
    latest_snapshot_sampled: bool | None = None,
) -> None:
    """Record observability counters for composite metric context payloads."""
    payload_scope = "device" if device_id is not None else "global"
    record_api_payload_request(endpoint=endpoint, scope=payload_scope)
    sections = (
        ("history", history_items, history_total, force_sampled or history_total > len(history_items)),
        (
            "selected_device_history",
            selected_device_history_items,
            selected_device_history_total,
            force_sampled or selected_device_history_total > len(selected_device_history_items),
        ),
        (
            "selected_device_trend",
            selected_device_trend_items,
            selected_device_trend_total,
            force_sampled or selected_device_trend_total > len(selected_device_trend_items),
        ),
        (
            "latest_snapshot",
            latest_snapshot_items,
            latest_snapshot_total,
            latest_snapshot_sampled
            if latest_snapshot_sampled is not None
            else latest_snapshot_total > len(latest_snapshot_items),
        ),
        (
            "selected_device_snapshot",
            selected_device_snapshot_items,
            selected_device_snapshot_total,
            force_sampled or selected_device_snapshot_total > len(selected_device_snapshot_items),
        ),
    )
    for section, items, total_rows, sampled in sections:
        record_api_payload_section(
            endpoint=endpoint,
            scope=payload_scope,
            section=section,
            rows=len(items),
            total_rows=total_rows,
            sampled=sampled,
        )


def _freshness_status(row: dict) -> str:
    """Return rollup freshness status for one collector/site bucket."""
    total_devices = int(row.get("total_devices") or 0)
    no_data_devices = int(row.get("no_data_devices") or 0)
    stale_devices = int(row.get("stale_devices") or 0)
    fresh_devices = int(row.get("fresh_devices") or 0)
    if total_devices <= 0 or no_data_devices >= total_devices:
        return "no_data"
    if stale_devices or no_data_devices:
        return "stale"
    if fresh_devices >= total_devices:
        return "fresh"
    return "unknown"
