from __future__ import annotations

from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.incident_repository import IncidentRepository
from ..repositories.metric_repository import MetricRepository
from ..services.monitoring_service import utcnow
from ..services.threshold_service import get_threshold_map
from .notifiers.telegram_notifier import send_telegram_alert
from .rules import ALERT_RULES


def evaluate_alerts(db) -> list[dict]:
    alert_repository = AlertRepository(db)
    incident_repository = IncidentRepository(db)
    latest_metrics = MetricRepository(db).latest_metric_map()
    devices = DeviceRepository(db).list_devices(active_only=True)
    notifications: list[dict] = []
    thresholds = get_threshold_map(db)

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
            try:
                ping_value = float(ping_metric.metric_value)
            except (TypeError, ValueError):
                ping_value = None

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
            try:
                value = float(metric.metric_value)
            except (TypeError, ValueError):
                continue

            if value >= threshold:
                expected_alerts[(device.id, alert_type)] = _build_alert_payload(
                    device_id=device.id,
                    alert_type=alert_type,
                    message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
                )

    active_alerts = {(alert.device_id, alert.alert_type): alert for alert in alert_repository.list_active_alerts()}

    for key, payload in expected_alerts.items():
        if key in active_alerts:
            continue
        created_alert = alert_repository.create_alert(payload)
        incident_action = _ensure_incident_for_alert(incident_repository, created_alert.device_id, created_alert.message)
        notification = {
            "action": "created",
            "alert_type": created_alert.alert_type,
            "device_id": created_alert.device_id,
            "message": created_alert.message,
            "incident_action": incident_action,
        }
        notifications.append(notification)
        send_telegram_alert(created_alert.message)

    resolved_at = utcnow()
    for key, alert in active_alerts.items():
        if key in expected_alerts:
            continue
        alert_repository.resolve_alert(alert, resolved_at)
        incident_action = _resolve_incident_if_cleared(incident_repository, alert_repository, alert.device_id, resolved_at)
        notifications.append(
            {
                "action": "resolved",
                "alert_type": alert.alert_type,
                "device_id": alert.device_id,
                "message": alert.message,
                "incident_action": incident_action,
            }
        )

    return notifications


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_alert_payload(device_id: int | None, alert_type: str, message: str) -> dict:
    rule = ALERT_RULES[alert_type]
    return {
        "device_id": device_id,
        "alert_type": alert_type,
        "severity": rule["severity"],
        "message": message,
        "status": "active",
        "created_at": utcnow(),
    }


def _ensure_incident_for_alert(incident_repository: IncidentRepository, device_id: int | None, message: str) -> str | None:
    active_incident = incident_repository.get_active_incident_by_device(device_id)
    if active_incident is not None:
        return None
    incident_repository.create_incident(
        {
            "device_id": device_id,
            "status": "active",
            "summary": message,
            "started_at": utcnow(),
        }
    )
    return "created"


def _resolve_incident_if_cleared(
    incident_repository: IncidentRepository,
    alert_repository: AlertRepository,
    device_id: int | None,
    resolved_at,
) -> str | None:
    remaining_alerts = [alert for alert in alert_repository.list_active_alerts() if alert.device_id == device_id]
    if remaining_alerts:
        return None
    active_incident = incident_repository.get_active_incident_by_device(device_id)
    if active_incident is None:
        return None
    incident_repository.resolve_incident(active_incident, resolved_at)
    return "resolved"
