"""Define module logic for `backend/app/alerting/engine.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from shared.device_utils import is_mikrotik_device
from shared.number_utils import safe_float

from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.incident_repository import IncidentRepository
from ..repositories.metric_repository import MetricRepository
from ..core.time import utcnow
from ..models.incident import Incident
from ..services.threshold_service import get_threshold_map
from .notifiers.telegram_notifier import send_telegram_alert
from .rules import ALERT_RULES


TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE = {
    "voip": {
        "high_ping_latency_warning",
        "high_ping_latency_critical",
        "high_packet_loss_warning",
        "high_packet_loss_critical",
        "high_jitter_warning",
        "high_jitter_critical",
    },
    "printer": {
        "high_ping_latency_warning",
        "high_ping_latency_critical",
        "high_jitter_warning",
        "high_jitter_critical",
    },
}
TELEGRAM_NOTIFICATION_DEDUPE_TTL = timedelta(minutes=5)
_recent_telegram_notification_keys: dict[tuple, object] = {}


async def evaluate_alerts(db, *, commit: bool = True) -> list[dict]:
    """Return evaluate alerts.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    alert_repository = AlertRepository(db)
    incident_repository = IncidentRepository(db)
    metric_repository = MetricRepository(db)
    device_repository = DeviceRepository(db)
    latest_metrics = await metric_repository.latest_metric_map()
    devices = await device_repository.list_devices(active_only=True)
    device_by_id = {device.id: device for device in devices}
    device_type_by_id = {device.id: device.device_type for device in devices}
    notifications: list[dict] = []
    telegram_events: list[dict] = []
    thresholds = await get_threshold_map(db, commit=commit)
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
            value = safe_float(metric.metric_value)
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
            dns_value = safe_float(dns_metric.metric_value)
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
            http_value = safe_float(http_metric.metric_value)
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

        if is_mikrotik_device(device.device_type, device.name):
            _evaluate_mikrotik_alerts(
                device=device,
                latest_metrics=latest_metrics,
                thresholds=thresholds,
                expected_alerts=expected_alerts,
            )

        if device.device_type == "printer":
            uptime_metric = latest_metrics.get((device.id, "printer_uptime_seconds"))
            current_uptime = safe_float(uptime_metric.metric_value) if uptime_metric is not None else None
            if current_uptime is not None:
                uptime_history = printer_uptime_history_by_device.get(device.id, [])
                if len(uptime_history) >= 2:
                    previous_uptime = safe_float(uptime_history[1].metric_value)
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
        created_alert_device_type = (
            device_type_by_id.get(created_alert.device_id) if created_alert.device_id is not None else None
        )
        if _should_send_telegram_alert(created_alert.alert_type, created_alert_device_type):
            telegram_events.append(
                {
                    "action": "active",
                    "alert_id": created_alert.id,
                    "alert_type": created_alert.alert_type,
                    "severity": created_alert.severity,
                    "message": created_alert.message,
                    "device": device_by_id.get(created_alert.device_id),
                }
            )

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
        resolved_alert_device_type = device_type_by_id.get(alert.device_id) if alert.device_id is not None else None
        notifications.append(
            {
                "action": "resolved",
                "alert_type": alert.alert_type,
                "device_id": alert.device_id,
                "message": alert.message,
                "incident_action": incident_action,
            }
        )
        if _should_send_telegram_alert(alert.alert_type, resolved_alert_device_type):
            telegram_events.append(
                {
                    "action": "resolved",
                    "alert_id": alert.id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "device": device_by_id.get(alert.device_id),
                    "created_at": alert.created_at,
                    "resolved_at": resolved_at,
                }
            )

    if has_pending_writes:
        if commit:
            await db.commit()
        else:
            await db.flush()
    telegram_messages = _build_telegram_messages(_filter_recent_telegram_events(telegram_events))
    if telegram_messages:
        await asyncio.gather(
            *(send_telegram_alert(message) for message in telegram_messages),
            return_exceptions=True,
        )

    return notifications


def _metric_numeric_value(metric) -> float | None:
    """Perform metric numeric value.

    Args:
        metric: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    numeric_value = getattr(metric, "metric_value_numeric", None)
    if numeric_value is not None:
        try:
            return float(numeric_value)
        except (TypeError, ValueError):
            pass
    return safe_float(getattr(metric, "metric_value", None))


def _should_send_telegram_alert(alert_type: str, device_type: str | None) -> bool:
    """Return whether an alert state change should be sent to Telegram."""
    return alert_type not in TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE.get(str(device_type or ""), set())


def _filter_recent_telegram_events(events: list[dict]) -> list[dict]:
    """Suppress duplicate Telegram events for the same alert state change."""
    if not events:
        return []
    current_time = utcnow()
    expired_keys = [
        key
        for key, last_seen_at in _recent_telegram_notification_keys.items()
        if last_seen_at <= current_time - TELEGRAM_NOTIFICATION_DEDUPE_TTL
    ]
    for key in expired_keys:
        _recent_telegram_notification_keys.pop(key, None)

    filtered_events: list[dict] = []
    for event in events:
        notification_key = _telegram_notification_key(event)
        if notification_key in _recent_telegram_notification_keys:
            continue
        _recent_telegram_notification_keys[notification_key] = current_time
        filtered_events.append(event)
    return filtered_events


def _telegram_notification_key(event: dict) -> tuple:
    """Build a stable dedupe key for one Telegram alert event."""
    device = event.get("device")
    return (
        str(event.get("action") or "active").lower(),
        getattr(device, "id", None),
        event.get("alert_id"),
        str(event.get("alert_type") or ""),
    )


def _build_telegram_messages(events: list[dict]) -> list[str]:
    """Build grouped Telegram messages for alert state changes."""
    grouped_events: dict[tuple[int | None, str], list[dict]] = {}
    for event in events:
        device = event.get("device")
        group_key = (getattr(device, "id", None), str(event.get("action") or "active").lower())
        grouped_events.setdefault(group_key, []).append(event)
    return [_build_telegram_message(group) for group in grouped_events.values()]


def _build_telegram_message(events: list[dict]) -> str:
    """Build Telegram message for one device and one alert state."""
    first_event = events[0]
    action = str(first_event.get("action") or "").lower()
    is_resolved = str(action or "").lower() == "resolved"
    title = "ALERT RESOLVED" if is_resolved else "ALERT ACTIVE"
    status = "RESOLVED" if is_resolved else "ACTIVE"
    severity = _highest_severity(str(event.get("severity") or "unknown") for event in events)
    device = first_event.get("device")
    device_name = getattr(device, "name", None) or "-"
    ip_address = getattr(device, "ip_address", None) or "-"
    site = getattr(device, "site", None) or "-"
    device_type = getattr(device, "device_type", None) or "-"
    alert_lines = [
        _format_telegram_alert_line(event, include_duration=is_resolved)
        for event in sorted(events, key=lambda item: str(item.get("alert_type") or ""))
    ]
    return "\n".join(
        [
            f"[{str(severity or 'unknown').upper()}] {title}",
            f"Device: {device_name}",
            f"IP: {ip_address}",
            f"Site: {site}",
            f"Type: {device_type}",
            f"Status: {status}",
            "Alerts:",
            *alert_lines,
        ]
    )


def _format_telegram_alert_line(event: dict, *, include_duration: bool) -> str:
    """Format one Telegram alert line, optionally including resolved duration."""
    line = f"- {event['alert_type']}: {event['message']}"
    if not include_duration:
        return line

    duration = _format_alert_duration(event.get("created_at"), event.get("resolved_at"))
    if duration is None:
        return line
    return f"{line} (duration: {duration})"


def _format_alert_duration(started_at, resolved_at) -> str | None:
    """Format elapsed alert duration for resolved Telegram notifications."""
    if started_at is None or resolved_at is None:
        return None

    total_seconds = int(max((resolved_at - started_at).total_seconds(), 0))
    if total_seconds < 60:
        return f"{max(total_seconds, 1)}s"

    total_minutes, seconds = divmod(total_seconds, 60)
    if total_minutes < 60:
        return f"{total_minutes}m {seconds}s" if seconds else f"{total_minutes}m"

    total_hours, minutes = divmod(total_minutes, 60)
    if total_hours < 24:
        return f"{total_hours}h {minutes}m" if minutes else f"{total_hours}h"

    days, hours = divmod(total_hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def _highest_severity(severities) -> str:
    """Return highest severity label from an iterable."""
    severity_order = {"critical": 3, "high": 2, "warning": 1, "unknown": 0}
    normalized = [str(severity or "unknown").lower() for severity in severities]
    if not normalized:
        return "unknown"
    return max(normalized, key=lambda severity: severity_order.get(severity, 0))


def _evaluate_mikrotik_alerts(*, device, latest_metrics: dict, thresholds: dict[str, float], expected_alerts: dict) -> None:
    """Perform evaluate mikrotik alerts.

    Args:
        device: Parameter input untuk routine ini.
        latest_metrics: Parameter input untuk routine ini.
        thresholds: Parameter input untuk routine ini.
        expected_alerts: Parameter input untuk routine ini.

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


def _highest_dynamic_metric(latest_metrics: dict, *, device_id: int, prefix: str, suffixes: tuple[str, ...]):
    """Perform highest dynamic metric.

    Args:
        latest_metrics: Parameter input untuk routine ini.
        device_id: Parameter input untuk routine ini.
        prefix: Parameter input untuk routine ini.
        suffixes: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    matches = [
        (metric_name, metric)
        for (current_device_id, metric_name), metric in latest_metrics.items()
        if current_device_id == device_id and str(metric_name).startswith(prefix) and str(metric_name).endswith(suffixes)
    ]
    numeric_matches = [
        (metric_name, metric, value)
        for metric_name, metric in matches
        if (value := safe_float(metric.metric_value)) is not None
    ]
    if not numeric_matches:
        return None
    metric_name, metric, _value = max(numeric_matches, key=lambda item: item[2])
    return metric_name, metric


def _build_alert_payload(device_id: int | None, alert_type: str, message: str) -> dict:
    """Build alert payload.

    Args:
        device_id: Parameter input untuk routine ini.
        alert_type: Parameter input untuk routine ini.
        message: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

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
    active_incidents_by_device: dict[int | None, Incident],
    device_id: int | None,
    message: str,
) -> str | None:
    """Ensure incident for alert.

    Args:
        incident_repository: Parameter input untuk routine ini.
        active_incidents_by_device: Parameter input untuk routine ini.
        device_id: Parameter input untuk routine ini.
        message: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

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
    active_incidents_by_device: dict[int | None, Incident],
    active_alert_count_by_device: dict[int | None, int],
    device_id: int | None,
    resolved_at,
) -> str | None:
    """Resolve incident if cleared.

    Args:
        incident_repository: Parameter input untuk routine ini.
        active_incidents_by_device: Parameter input untuk routine ini.
        active_alert_count_by_device: Parameter input untuk routine ini.
        device_id: Parameter input untuk routine ini.
        resolved_at: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

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
