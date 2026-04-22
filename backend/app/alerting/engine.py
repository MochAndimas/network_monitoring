"""Provide alert evaluation and notification workflows for the network monitoring project."""

from __future__ import annotations

import asyncio

from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.incident_repository import IncidentRepository
from ..repositories.metric_repository import MetricRepository
from ..core.time import utcnow
from ..services.threshold_service import get_threshold_map
from .notifiers.telegram_notifier import send_telegram_alert
from .rules import ALERT_RULES


async def evaluate_alerts(db) -> list[dict]:
    """Handle evaluate alerts for alert evaluation and notification workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine.

    Returns:
        `list[dict]` result produced by the routine.
    """
    alert_repository = AlertRepository(db)
    incident_repository = IncidentRepository(db)
    metric_repository = MetricRepository(db)
    device_repository = DeviceRepository(db)
    latest_metrics = await metric_repository.latest_metric_map()
    devices = await device_repository.list_devices(active_only=True)
    notifications: list[dict] = []
    telegram_messages: list[str] = []
    thresholds = await get_threshold_map(db)
    active_alerts = {(alert.device_id, alert.alert_type): alert for alert in await alert_repository.list_active_alerts()}
    active_incidents_by_device = {
        incident.device_id: incident for incident in await incident_repository.list_active_incidents()
    }
    printer_device_ids = [device.id for device in devices if device.device_type == "printer"]
    printer_uptime_history_by_device = (
        await metric_repository.list_recent_metrics_by_device(
            device_ids=printer_device_ids,
            metric_name="printer_uptime_seconds",
            per_device_limit=2,
        )
        if printer_device_ids
        else {}
    )
    active_alert_count_by_device: dict[int | None, int] = {}
    for alert in active_alerts.values():
        active_alert_count_by_device[alert.device_id] = active_alert_count_by_device.get(alert.device_id, 0) + 1
    has_pending_writes = False

    expected_alerts: dict[tuple[int | None, str], dict] = {}

    for device in devices:
        ping_metric = latest_metrics.get((device.id, "ping"))
        if ping_metric is not None and ping_metric.status == "down":
            alert_type = "internet_loss" if device.device_type == "internet_target" else "device_down"
            expected_alerts[(device.id, alert_type)] = _build_alert_payload(
                device_id=device.id,
                alert_type=alert_type,
                message=f"{device.name} is unreachable",
            )
        elif ping_metric is not None:
            ping_value = _metric_numeric_value(ping_metric)

            if ping_value is not None:
                if ping_value >= thresholds["ping_latency_critical"]:
                    expected_alerts[(device.id, "high_ping_latency_critical")] = _build_alert_payload(
                        device_id=device.id,
                        alert_type="high_ping_latency_critical",
                        message=f"{device.name} ping latency reached {ping_value:.2f}{ping_metric.unit or ''}",
                    )
                elif ping_value >= thresholds["ping_latency_warning"]:
                    expected_alerts[(device.id, "high_ping_latency_warning")] = _build_alert_payload(
                        device_id=device.id,
                        alert_type="high_ping_latency_warning",
                        message=f"{device.name} ping latency reached {ping_value:.2f}{ping_metric.unit or ''}",
                    )

        for metric_name, warning_alert, critical_alert, warning_threshold, critical_threshold in [
            (
                "packet_loss",
                "high_packet_loss_warning",
                "high_packet_loss_critical",
                thresholds["packet_loss_warning"],
                thresholds["packet_loss_critical"],
            ),
            (
                "jitter",
                "high_jitter_warning",
                "high_jitter_critical",
                thresholds["jitter_warning"],
                thresholds["jitter_critical"],
            ),
        ]:
            metric = latest_metrics.get((device.id, metric_name))
            if metric is None:
                continue
            value = _safe_float(metric.metric_value)
            if value is None:
                continue
            if value >= critical_threshold:
                expected_alerts[(device.id, critical_alert)] = _build_alert_payload(
                    device_id=device.id,
                    alert_type=critical_alert,
                    message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
                )
            elif value >= warning_threshold:
                expected_alerts[(device.id, warning_alert)] = _build_alert_payload(
                    device_id=device.id,
                    alert_type=warning_alert,
                    message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
                )

        dns_metric = latest_metrics.get((device.id, "dns_resolution_time"))
        if dns_metric is not None:
            dns_value = _safe_float(dns_metric.metric_value)
            if dns_metric.status == "down":
                expected_alerts[(device.id, "dns_resolution_failed")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="dns_resolution_failed",
                    message=f"{device.name} DNS resolution failed",
                )
            elif dns_value is not None and dns_value >= thresholds["dns_resolution_warning"]:
                expected_alerts[(device.id, "slow_dns_resolution")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="slow_dns_resolution",
                    message=f"{device.name} DNS resolution reached {dns_value:.2f}{dns_metric.unit or ''}",
                )

        http_metric = latest_metrics.get((device.id, "http_response_time"))
        if http_metric is not None:
            http_value = _safe_float(http_metric.metric_value)
            if http_metric.status == "down":
                expected_alerts[(device.id, "http_check_failed")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="http_check_failed",
                    message=f"{device.name} HTTP check failed",
                )
            elif http_value is not None and http_value >= thresholds["http_response_warning"]:
                expected_alerts[(device.id, "slow_http_response")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="slow_http_response",
                    message=f"{device.name} HTTP response reached {http_value:.2f}{http_metric.unit or ''}",
                )

        public_ip_metric = latest_metrics.get((device.id, "public_ip"))
        if public_ip_metric is not None and public_ip_metric.status == "warning":
            expected_alerts[(device.id, "public_ip_changed")] = _build_alert_payload(
                device_id=device.id,
                alert_type="public_ip_changed",
                message=f"{device.name} public IP changed to {public_ip_metric.metric_value}",
            )

        for metric_name, alert_type, threshold in [
            ("cpu_percent", "high_cpu", thresholds["cpu_warning"]),
            ("memory_percent", "high_ram", thresholds["ram_warning"]),
            ("disk_percent", "high_disk", thresholds["disk_warning"]),
        ]:
            metric = latest_metrics.get((device.id, metric_name))
            if metric is None:
                continue
            value = _metric_numeric_value(metric)
            if value is None:
                continue

            if value >= threshold:
                expected_alerts[(device.id, alert_type)] = _build_alert_payload(
                    device_id=device.id,
                    alert_type=alert_type,
                    message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
                )

        if _is_mikrotik_device(device):
            _evaluate_mikrotik_alerts(
                device=device,
                latest_metrics=latest_metrics,
                thresholds=thresholds,
                expected_alerts=expected_alerts,
            )

        if device.device_type == "printer":
            uptime_metric = latest_metrics.get((device.id, "printer_uptime_seconds"))
            current_uptime = _safe_float(uptime_metric.metric_value) if uptime_metric is not None else None
            if current_uptime is not None:
                uptime_history = printer_uptime_history_by_device.get(device.id, [])
                if len(uptime_history) >= 2:
                    previous_uptime = _safe_float(uptime_history[1].metric_value)
                    if previous_uptime is not None and current_uptime < previous_uptime:
                        expected_alerts[(device.id, "printer_reboot_detected")] = _build_alert_payload(
                            device_id=device.id,
                            alert_type="printer_reboot_detected",
                            message=f"{device.name} appears to have rebooted; uptime reset to {int(current_uptime)}s",
                        )

            printer_status_metric = latest_metrics.get((device.id, "printer_status"))
            if printer_status_metric is not None and printer_status_metric.status == "warning":
                expected_alerts[(device.id, "printer_status_warning")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="printer_status_warning",
                    message=f"{device.name} reported printer status {printer_status_metric.metric_value}",
                )

            printer_error_metric = latest_metrics.get((device.id, "printer_error_state"))
            if printer_error_metric is not None and printer_error_metric.metric_value not in {"", "none"}:
                expected_alerts[(device.id, "printer_error_state")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="printer_error_state",
                    message=f"{device.name} printer error state: {printer_error_metric.metric_value.replace(',', ', ')}",
                )

            printer_paper_metric = latest_metrics.get((device.id, "printer_paper_status"))
            if printer_paper_metric is not None and printer_paper_metric.metric_value not in {"", "ok"}:
                expected_alerts[(device.id, "printer_paper_issue")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="printer_paper_issue",
                    message=f"{device.name} paper status is {printer_paper_metric.metric_value}",
                )

            printer_ink_status_metric = latest_metrics.get((device.id, "printer_ink_status"))
            if printer_ink_status_metric is not None and printer_ink_status_metric.metric_value == "empty":
                expected_alerts[(device.id, "printer_ink_empty")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="printer_ink_empty",
                    message=f"{device.name} ink status is empty",
                )
            elif printer_ink_status_metric is not None and printer_ink_status_metric.metric_value == "low":
                expected_alerts[(device.id, "printer_ink_low")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="printer_ink_low",
                    message=f"{device.name} ink status is low",
                )

    for key, payload in expected_alerts.items():
        if key in active_alerts:
            continue
        created_alert = await alert_repository.create_alert(payload, commit=False)
        active_alerts[key] = created_alert
        active_alert_count_by_device[created_alert.device_id] = active_alert_count_by_device.get(created_alert.device_id, 0) + 1
        incident_action = await _ensure_incident_for_alert(
            incident_repository,
            active_incidents_by_device,
            created_alert.device_id,
            created_alert.message,
        )
        has_pending_writes = True
        notification = {
            "action": "created",
            "alert_type": created_alert.alert_type,
            "device_id": created_alert.device_id,
            "message": created_alert.message,
            "incident_action": incident_action,
        }
        notifications.append(notification)
        telegram_messages.append(created_alert.message)

    resolved_at = utcnow()
    for key, alert in list(active_alerts.items()):
        if key in expected_alerts:
            continue
        await alert_repository.resolve_alert(alert, resolved_at, commit=False)
        incident_action = await _resolve_incident_if_cleared(
            incident_repository,
            active_incidents_by_device,
            active_alert_count_by_device,
            alert.device_id,
            resolved_at,
        )
        has_pending_writes = True
        active_alerts.pop(key, None)
        notifications.append(
            {
                "action": "resolved",
                "alert_type": alert.alert_type,
                "device_id": alert.device_id,
                "message": alert.message,
                "incident_action": incident_action,
            }
        )

    if has_pending_writes:
        await db.commit()
    if telegram_messages:
        await asyncio.gather(
            *(send_telegram_alert(message) for message in telegram_messages),
            return_exceptions=True,
        )

    return notifications


def _safe_float(value: str | None) -> float | None:
    """Handle the internal safe float helper logic for alert evaluation and notification workflows.

    Args:
        value: value value used by this routine (type `str | None`).

    Returns:
        `float | None` result produced by the routine.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_numeric_value(metric) -> float | None:
    """Handle the internal metric numeric value helper logic for alert evaluation and notification workflows.

    Args:
        metric: metric value used by this routine.

    Returns:
        `float | None` result produced by the routine.
    """
    numeric_value = getattr(metric, "metric_value_numeric", None)
    if numeric_value is not None:
        try:
            return float(numeric_value)
        except (TypeError, ValueError):
            pass
    return _safe_float(getattr(metric, "metric_value", None))


def _is_mikrotik_device(device) -> bool:
    """Handle the internal is mikrotik device helper logic for alert evaluation and notification workflows.

    Args:
        device: device value used by this routine.

    Returns:
        `bool` result produced by the routine.
    """
    return str(device.device_type or "").lower() == "mikrotik" or "mikrotik" in str(device.name or "").lower()


def _evaluate_mikrotik_alerts(*, device, latest_metrics: dict, thresholds: dict[str, float], expected_alerts: dict) -> None:
    """Handle the internal evaluate mikrotik alerts helper logic for alert evaluation and notification workflows.

    Args:
        device: device keyword value used by this routine.
        latest_metrics: latest metrics keyword value used by this routine (type `dict`).
        thresholds: thresholds keyword value used by this routine (type `dict[str, float]`).
        expected_alerts: expected alerts keyword value used by this routine (type `dict`).

    Returns:
        None. The routine is executed for its side effects.
    """
    api_metric = latest_metrics.get((device.id, "mikrotik_api"))
    if api_metric is not None and (
        str(api_metric.status or "").lower() == "error" or str(api_metric.metric_value or "") == "connection_failed"
    ):
        expected_alerts[(device.id, "mikrotik_api_failed")] = _build_alert_payload(
            device_id=device.id,
            alert_type="mikrotik_api_failed",
            message=f"{device.name} Mikrotik API connection failed",
        )

    client_metric = latest_metrics.get((device.id, "connected_clients"))
    client_count = _safe_float(client_metric.metric_value) if client_metric is not None else None
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
        value = _safe_float(metric.metric_value)
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
        value = _safe_float(metric.metric_value)
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


def _highest_dynamic_metric(latest_metrics: dict, *, device_id: int, prefix: str, suffixes: tuple[str, ...]):
    """Handle the internal highest dynamic metric helper logic for alert evaluation and notification workflows.

    Args:
        latest_metrics: latest metrics value used by this routine (type `dict`).
        device_id: device id keyword value used by this routine (type `int`).
        prefix: prefix keyword value used by this routine (type `str`).
        suffixes: suffixes keyword value used by this routine (type `tuple[str, ...]`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    matches = [
        (metric_name, metric)
        for (current_device_id, metric_name), metric in latest_metrics.items()
        if current_device_id == device_id and str(metric_name).startswith(prefix) and str(metric_name).endswith(suffixes)
    ]
    numeric_matches = [
        (metric_name, metric, value)
        for metric_name, metric in matches
        if (value := _safe_float(metric.metric_value)) is not None
    ]
    if not numeric_matches:
        return None
    metric_name, metric, _value = max(numeric_matches, key=lambda item: item[2])
    return metric_name, metric


def _build_alert_payload(device_id: int | None, alert_type: str, message: str) -> dict:
    """Build alert payload for alert evaluation and notification workflows.

    Args:
        device_id: device id value used by this routine (type `int | None`).
        alert_type: alert type value used by this routine (type `str`).
        message: message value used by this routine (type `str`).

    Returns:
        `dict` result produced by the routine.
    """
    rule = ALERT_RULES[alert_type]
    return {
        "device_id": device_id,
        "alert_type": alert_type,
        "severity": rule["severity"],
        "message": message,
        "status": "active",
        "created_at": utcnow(),
    }


async def _ensure_incident_for_alert(
    incident_repository: IncidentRepository,
    active_incidents_by_device: dict[int | None, object],
    device_id: int | None,
    message: str,
) -> str | None:
    """Ensure incident for alert for alert evaluation and notification workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        incident_repository: incident repository value used by this routine (type `IncidentRepository`).
        active_incidents_by_device: active incidents by device value used by this routine (type `dict[int | None, object]`).
        device_id: device id value used by this routine (type `int | None`).
        message: message value used by this routine (type `str`).

    Returns:
        `str | None` result produced by the routine.
    """
    active_incident = active_incidents_by_device.get(device_id)
    if active_incident is not None:
        return None
    created_incident = await incident_repository.create_incident(
        {
            "device_id": device_id,
            "status": "active",
            "summary": message,
            "started_at": utcnow(),
        },
        commit=False,
    )
    active_incidents_by_device[device_id] = created_incident
    return "created"


async def _resolve_incident_if_cleared(
    incident_repository: IncidentRepository,
    active_incidents_by_device: dict[int | None, object],
    active_alert_count_by_device: dict[int | None, int],
    device_id: int | None,
    resolved_at,
) -> str | None:
    """Resolve incident if cleared for alert evaluation and notification workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        incident_repository: incident repository value used by this routine (type `IncidentRepository`).
        active_incidents_by_device: active incidents by device value used by this routine (type `dict[int | None, object]`).
        active_alert_count_by_device: active alert count by device value used by this routine (type `dict[int | None, int]`).
        device_id: device id value used by this routine (type `int | None`).
        resolved_at: resolved at value used by this routine.

    Returns:
        `str | None` result produced by the routine.
    """
    remaining_count = max(active_alert_count_by_device.get(device_id, 0) - 1, 0)
    active_alert_count_by_device[device_id] = remaining_count
    if remaining_count:
        return None
    active_incident = active_incidents_by_device.get(device_id)
    if active_incident is None:
        return None
    await incident_repository.resolve_incident(active_incident, resolved_at, commit=False)
    active_incidents_by_device.pop(device_id, None)
    return "resolved"
