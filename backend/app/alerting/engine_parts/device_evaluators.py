"""Device-type-specific alert evaluators."""

from collections.abc import Mapping

from shared.number_utils import safe_float

from ...models.device import Device
from ...models.metric import Metric
from .utils import _build_alert_payload, _highest_dynamic_metric, _metric_numeric_value


def evaluate_mikrotik_alerts(
    *,
    device: Device,
    latest_metrics: Mapping[tuple[int, str], Metric],
    thresholds: Mapping[str, float],
    expected_alerts: dict[tuple[int | None, str], dict],
) -> None:
    """Add Mikrotik-specific expected alerts for API, client, interface, and firewall metrics."""
    api_metric = latest_metrics.get((device.id, "mikrotik_api"))
    if api_metric is not None and str(api_metric.status or "").lower() == "error":
        expected_alerts[(device.id, "mikrotik_api_failed")] = _build_alert_payload(
            device_id=device.id,
            alert_type="mikrotik_api_failed",
            message=f"{device.name} Mikrotik API collection is {api_metric.metric_value}",
        )

    client_metric = latest_metrics.get((device.id, "connected_clients"))
    client_count = safe_float(client_metric.metric_value) if client_metric is not None else None
    if client_count is not None and client_count >= thresholds["mikrotik_connected_clients_warning"]:
        expected_alerts[(device.id, "mikrotik_connected_clients_high")] = _build_alert_payload(
            device_id=device.id,
            alert_type="mikrotik_connected_clients_high",
            message=f"{device.name} connected clients reached {int(client_count)}",
        )

    interface_spike = _highest_dynamic_metric(
        latest_metrics,
        device_id=device.id,
        prefix="interface:",
        suffixes=(":rx_mbps", ":tx_mbps"),
    )
    if interface_spike is not None:
        metric_name, metric = interface_spike
        value = safe_float(metric.metric_value)
        if value is not None and value >= thresholds["mikrotik_interface_mbps_warning"]:
            expected_alerts[(device.id, "mikrotik_interface_traffic_high")] = _build_alert_payload(
                device_id=device.id,
                alert_type="mikrotik_interface_traffic_high",
                message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
            )

    firewall_spike = _highest_dynamic_metric(
        latest_metrics,
        device_id=device.id,
        prefix="firewall:",
        suffixes=(":pps", ":mbps"),
    )
    if firewall_spike is not None:
        metric_name, metric = firewall_spike
        value = safe_float(metric.metric_value)
        threshold = (
            thresholds["mikrotik_firewall_spike_pps_warning"]
            if metric_name.endswith(":pps")
            else thresholds["mikrotik_firewall_spike_mbps_warning"]
        )
        if value is not None and (value >= threshold or str(metric.status or "").lower() == "warning"):
            expected_alerts[(device.id, "mikrotik_firewall_spike")] = _build_alert_payload(
                device_id=device.id,
                alert_type="mikrotik_firewall_spike",
                message=f"{device.name} firewall spike on {metric_name}: {value:.2f}{metric.unit or ''}",
            )


def evaluate_nas_alerts(
    *,
    device: Device,
    latest_metrics: Mapping[tuple[int, str], Metric],
    thresholds: Mapping[str, float],
    expected_alerts: dict[tuple[int | None, str], dict],
) -> None:
    """Add NAS-specific expected alerts for SNMP health metrics."""
    for metric_name, alert_type, label in [
        ("nas_system_status", "nas_system_status_problem", "system status"),
        ("nas_power_status", "nas_power_status_problem", "power status"),
    ]:
        metric = latest_metrics.get((device.id, metric_name))
        status_value = str(getattr(metric, "metric_value", "") or "").lower()
        if metric is not None and str(getattr(metric, "status", "")).lower() == "error" and status_value not in {"normal", "ok"}:
            expected_alerts[(device.id, alert_type)] = _build_alert_payload(
                device_id=device.id,
                alert_type=alert_type,
                message=f"{device.name} NAS {label} is {metric.metric_value}",
            )

    system_temperature_metric = latest_metrics.get((device.id, "nas_system_temperature_c"))
    system_temperature = _metric_numeric_value(system_temperature_metric) if system_temperature_metric is not None else None
    if system_temperature is not None and system_temperature >= thresholds["nas_system_temperature_warning"]:
        expected_alerts[(device.id, "nas_system_temperature_high")] = _build_alert_payload(
            device_id=device.id,
            alert_type="nas_system_temperature_high",
            message=f"{device.name} NAS system temperature reached {system_temperature:.2f}C",
        )

    _add_nas_status_alert(
        device=device,
        latest_metrics=latest_metrics,
        expected_alerts=expected_alerts,
        prefix="nas_fan:",
        suffix=":status",
        alert_type="nas_fan_status_problem",
        label="fan",
    )
    _add_nas_status_alert(
        device=device,
        latest_metrics=latest_metrics,
        expected_alerts=expected_alerts,
        prefix="nas_volume:",
        suffix=":status",
        alert_type="nas_volume_status_problem",
        label="volume",
    )
    _add_nas_status_alert(
        device=device,
        latest_metrics=latest_metrics,
        expected_alerts=expected_alerts,
        prefix="nas_raid:",
        suffix=":status",
        alert_type="nas_raid_status_problem",
        label="storage pool",
    )
    _add_nas_status_alert(
        device=device,
        latest_metrics=latest_metrics,
        expected_alerts=expected_alerts,
        prefix="nas_disk:",
        suffix=":status",
        alert_type="nas_disk_status_problem",
        label="disk",
        ok_values={"normal", "initialized", "ok"},
    )

    hot_disks: list[tuple[str, float]] = []
    for (current_device_id, metric_name), metric in latest_metrics.items():
        if (
            current_device_id != device.id
            or not str(metric_name).startswith("nas_disk:")
            or not str(metric_name).endswith(":temperature_c")
        ):
            continue
        temperature_value = _metric_numeric_value(metric)
        if temperature_value is not None and temperature_value >= thresholds["nas_disk_temperature_warning"]:
            hot_disks.append((metric_name, temperature_value))
    if hot_disks:
        metric_name, value = max(hot_disks, key=lambda item: item[1])
        expected_alerts[(device.id, "nas_disk_temperature_high")] = _build_alert_payload(
            device_id=device.id,
            alert_type="nas_disk_temperature_high",
            message=f"{device.name} NAS {metric_name} reached {value:.2f}C",
        )


def _add_nas_status_alert(
    *,
    device: Device,
    latest_metrics: Mapping[tuple[int, str], Metric],
    expected_alerts: dict[tuple[int | None, str], dict],
    prefix: str,
    suffix: str,
    alert_type: str,
    label: str,
    ok_values: set[str] | None = None,
) -> None:
    """Aggregate abnormal NAS dynamic status metrics into one alert type."""
    normalized_ok_values = ok_values or {"normal", "ok"}
    problems = []
    for (current_device_id, metric_name), metric in latest_metrics.items():
        if current_device_id != device.id or not str(metric_name).startswith(prefix) or not str(metric_name).endswith(suffix):
            continue
        value = str(getattr(metric, "metric_value", "") or "").lower()
        if str(getattr(metric, "status", "")).lower() == "error" and value not in normalized_ok_values:
            problems.append(f"{metric_name}={metric.metric_value}")
    if not problems:
        return
    expected_alerts[(device.id, alert_type)] = _build_alert_payload(
        device_id=device.id,
        alert_type=alert_type,
        message=f"{device.name} NAS {label} problem: {', '.join(problems[:3])}",
    )


_evaluate_mikrotik_alerts = evaluate_mikrotik_alerts
_evaluate_nas_alerts = evaluate_nas_alerts

__all__ = ["_evaluate_mikrotik_alerts", "_evaluate_nas_alerts", "evaluate_mikrotik_alerts", "evaluate_nas_alerts"]
