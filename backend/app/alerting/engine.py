from __future__ import annotations

from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.incident_repository import IncidentRepository
from ..repositories.metric_repository import MetricRepository
from ..services.monitoring_service import utcnow
from ..services.threshold_service import get_threshold_map
from .notifiers.telegram_notifier import send_telegram_alert
from .rules import ALERT_RULES


async def evaluate_alerts(db) -> list[dict]:
    alert_repository = AlertRepository(db)
    incident_repository = IncidentRepository(db)
    metric_repository = MetricRepository(db)
    device_repository = DeviceRepository(db)
    latest_metrics = await metric_repository.latest_metric_map()
    devices = await device_repository.list_devices(active_only=True)
    notifications: list[dict] = []
    thresholds = await get_threshold_map(db)
    active_alerts = {(alert.device_id, alert.alert_type): alert for alert in await alert_repository.list_active_alerts()}
    active_incidents_by_device = {
        incident.device_id: incident for incident in await incident_repository.list_active_incidents()
    }
    printer_uptime_history_by_device = await metric_repository.list_recent_metrics_by_device(
        device_ids=[device.id for device in devices if device.device_type == "printer"],
        metric_name="printer_uptime_seconds",
        per_device_limit=2,
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
        await send_telegram_alert(created_alert.message)

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


async def _ensure_incident_for_alert(
    incident_repository: IncidentRepository,
    active_incidents_by_device: dict[int | None, object],
    device_id: int | None,
    message: str,
) -> str | None:
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
