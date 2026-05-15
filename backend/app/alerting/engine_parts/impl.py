"""Alert evaluation, incident transitions, and notification orchestration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from ...core.config import settings
from ...core.time import utcnow
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...models.alert import Alert
from ...models.incident import Incident
from ...models.metric import Metric
from ...services.dashboard_overview_service import invalidate_dashboard_overview_cache
from ...services.threshold_service import get_threshold_map
from ..notifiers.telegram_notifier import send_telegram_alert
from ..rules import ALERT_RULES
from .constants import (
    ALERT_DYNAMIC_METRIC_NAME_PATTERNS,
    ALERT_EXACT_METRIC_NAMES,
    TELEGRAM_NOTIFICATION_DEDUPE_TTL,
    TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE,
)
from .device_evaluators import _evaluate_mikrotik_alerts as _evaluate_mikrotik_alerts
from .device_evaluators import _evaluate_nas_alerts as _evaluate_nas_alerts
from .evaluation_context import AlertEvaluationContext
from .rule_evaluators import evaluate_expected_alerts_for_device
from .utils import (
    _build_alert_payload as _build_alert_payload,
    _highest_dynamic_metric as _highest_dynamic_metric,
    _metric_numeric_value as _metric_numeric_value,
    _threshold_for_device as _threshold_for_device,
)


_recent_telegram_notification_keys: dict[tuple, datetime] = {}


async def evaluate_alerts(db, *, commit: bool = True) -> list[dict]:
    """Evaluate latest metrics, create or resolve alerts, maintain incidents, and queue notifications."""
    alert_repository = AlertRepository(db)
    incident_repository = IncidentRepository(db)
    metric_repository = MetricRepository(db)
    device_repository = DeviceRepository(db)
    latest_metrics = await metric_repository.latest_metric_map_for_alert_evaluation(
        exact_metric_names=ALERT_EXACT_METRIC_NAMES,
        dynamic_metric_name_patterns=ALERT_DYNAMIC_METRIC_NAME_PATTERNS,
    )
    active_alerts_list = await alert_repository.list_active_alerts_by_types(set(ALERT_RULES))
    active_alert_device_ids = {alert.device_id for alert in active_alerts_list if alert.device_id is not None}
    latest_metric_device_ids = {device_id for device_id, _metric_name in latest_metrics}
    candidate_device_ids = latest_metric_device_ids | active_alert_device_ids
    devices = await device_repository.list_devices_by_ids(candidate_device_ids, active_only=True)
    device_by_id = {device.id: device for device in devices}
    device_type_by_id = {device.id: device.device_type for device in devices}
    notifications: list[dict] = []
    telegram_events: list[dict] = []
    thresholds = await get_threshold_map(db, commit=commit)
    active_alerts = {(alert.device_id, alert.alert_type): alert for alert in active_alerts_list}
    active_alert_count_by_device: dict[int | None, int] = {}
    for alert in active_alerts.values():
        active_alert_count_by_device[alert.device_id] = active_alert_count_by_device.get(alert.device_id, 0) + 1
    active_incident_device_ids: set[int | None] = set(candidate_device_ids)
    active_incident_device_ids.update(
        device_id for device_id in active_alert_count_by_device if device_id is not None
    )
    active_incidents_by_device = _group_incidents_by_device(
        await incident_repository.list_active_incidents_by_device_ids(active_incident_device_ids)
    )
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
    internet_target_device_ids = [device.id for device in devices if device.device_type == "internet_target"]
    internet_service_history_by_device = await _load_internet_service_history_by_device(
        metric_repository,
        internet_target_device_ids,
    )
    has_pending_writes = False

    expected_alerts: dict[tuple[int | None, str], dict] = {}

    for device in devices:
        evaluate_expected_alerts_for_device(
            AlertEvaluationContext(
                device=device,
                latest_metrics=latest_metrics,
                thresholds=thresholds,
                expected_alerts=expected_alerts,
                printer_uptime_history_by_device=printer_uptime_history_by_device,
                internet_service_history_by_device=internet_service_history_by_device,
            )
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
        if _should_send_telegram_resolved_alert(alert, resolved_at, resolved_alert_device_type):
            telegram_events.append(
                {
                    "action": "resolved",
                    "alert_id": alert.id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "device": device_by_id.get(alert.device_id) if alert.device_id is not None else None,
                    "created_at": alert.created_at,
                    "resolved_at": resolved_at,
                }
            )

    orphan_incident_actions = await _resolve_orphan_incidents(
        incident_repository,
        active_incidents_by_device,
        active_alert_count_by_device,
        resolved_at,
    )
    if orphan_incident_actions:
        has_pending_writes = True
        notifications.extend(orphan_incident_actions)

    if has_pending_writes:
        if commit:
            await db.commit()
        else:
            await db.flush()
        invalidate_dashboard_overview_cache()
    telegram_events.extend(
        _pending_active_telegram_events(
            active_alerts.values(),
            device_by_id=device_by_id,
            device_type_by_id=device_type_by_id,
        )
    )
    await _send_telegram_events(
        db,
        alert_repository,
        _filter_recent_telegram_events(telegram_events),
        commit=commit,
    )

    return notifications


def _should_send_telegram_alert(alert_type: str, device_type: str | None) -> bool:
    """Return whether an alert state change should be sent to Telegram."""
    return alert_type not in TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE.get(str(device_type or ""), set())


def _should_send_telegram_resolved_alert(alert, resolved_at, device_type: str | None) -> bool:
    """Return whether a resolved alert should be sent to Telegram."""
    if not _should_send_telegram_alert(alert.alert_type, device_type):
        return False
    return alert.telegram_notified_at is not None


def _alert_reached_telegram_grace_period(started_at: datetime | None, current_time: datetime | None) -> bool:
    """Return whether an alert has stayed active long enough for Telegram."""
    if started_at is None or current_time is None:
        return False
    grace_period = timedelta(seconds=max(int(settings.telegram.alert_grace_period_seconds or 0), 0))
    return started_at <= current_time - grace_period


def _pending_active_telegram_events(alerts, *, device_by_id: dict, device_type_by_id: dict) -> list[dict]:
    """Return active alerts that have aged past the Telegram grace period."""
    current_time = utcnow()
    events: list[dict] = []
    for alert in alerts:
        device_type = device_type_by_id.get(alert.device_id) if alert.device_id is not None else None
        if alert.telegram_notified_at is not None:
            continue
        if not _should_send_telegram_alert(alert.alert_type, device_type):
            continue
        if not _alert_reached_telegram_grace_period(alert.created_at, current_time):
            continue
        events.append(
            {
                "action": "active",
                "alert": alert,
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "device": device_by_id.get(alert.device_id),
            }
        )
    return events


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
    return [_build_telegram_message(group) for group in _group_telegram_events(events).values()]


def _group_telegram_events(events: list[dict]) -> dict[tuple[int | None, str], list[dict]]:
    """Group Telegram events by device and alert state."""
    grouped_events: dict[tuple[int | None, str], list[dict]] = {}
    for event in events:
        device = event.get("device")
        group_key = (getattr(device, "id", None), str(event.get("action") or "active").lower())
        grouped_events.setdefault(group_key, []).append(event)
    return grouped_events


def _order_telegram_events(events: list[dict]) -> list[dict]:
    """Keep active notifications ahead of resolved notifications in the same send batch."""
    action_rank = {"active": 0, "created": 0, "resolved": 1}
    return sorted(events, key=lambda event: action_rank.get(str(event.get("action") or "active").lower(), 0))


async def _send_telegram_events(db, alert_repository: AlertRepository, events: list[dict], *, commit: bool) -> None:
    """Send Telegram events and mark active alerts that were successfully delivered."""
    events = _order_telegram_events(await _refresh_telegram_events(db, events))
    grouped_events = _group_telegram_events(events)
    if not grouped_events:
        return

    grouped_items = list(grouped_events.values())
    results = await asyncio.gather(
        *(send_telegram_alert(_build_telegram_message(group)) for group in grouped_items),
        return_exceptions=True,
    )
    notified_at = utcnow()
    has_marked_alerts = False
    for group, result in zip(grouped_items, results, strict=True):
        if isinstance(result, Exception):
            continue
        for event in group:
            if str(event.get("action") or "active").lower() != "active":
                continue
            alert = event.get("alert")
            if alert is None:
                continue
            await alert_repository.mark_telegram_notified(alert, notified_at, commit=False)
            has_marked_alerts = True

    if has_marked_alerts:
        if commit:
            await db.commit()
        else:
            await db.flush()


async def _refresh_telegram_events(db, events: list[dict]) -> list[dict]:
    """Re-read active events before sending so stale ACTIVE messages do not outlive resolved alerts."""
    refreshed_events: list[dict] = []
    for event in events:
        if str(event.get("action") or "active").lower() != "active":
            refreshed_events.append(event)
            continue

        alert_id = event.get("alert_id")
        if alert_id is None:
            refreshed_events.append(event)
            continue

        fresh_alert = await db.get(Alert, alert_id)
        if fresh_alert is None or fresh_alert.telegram_notified_at is not None:
            continue
        fresh_event = {**event, "alert": fresh_alert}
        if str(fresh_alert.status or "").lower() == "active":
            refreshed_events.append(fresh_event)
            continue
        if str(fresh_alert.status or "").lower() == "resolved":
            continue
    return refreshed_events


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


def _group_incidents_by_device(incidents: list[Incident]) -> dict[int | None, list[Incident]]:
    """Group active incidents by device without dropping duplicate rows."""
    incidents_by_device: dict[int | None, list[Incident]] = {}
    for incident in incidents:
        incidents_by_device.setdefault(incident.device_id, []).append(incident)
    return incidents_by_device


async def _ensure_incident_for_alert(
    incident_repository: IncidentRepository,
    active_incidents_by_device: dict[int | None, list[Incident]],
    device_id: int | None,
    message: str,
) -> str | None:
    """Ensure incident for alert for alert evaluation."""
    active_incidents = active_incidents_by_device.get(device_id, [])
    if active_incidents:
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
    active_incidents_by_device[device_id] = [created_incident]
    return "created"


async def _resolve_incident_if_cleared(
    incident_repository: IncidentRepository,
    active_incidents_by_device: dict[int | None, list[Incident]],
    active_alert_count_by_device: dict[int | None, int],
    device_id: int | None,
    resolved_at,
) -> str | None:
    """Resolve incident if cleared for alert evaluation."""
    remaining_count = max(active_alert_count_by_device.get(device_id, 0) - 1, 0)
    active_alert_count_by_device[device_id] = remaining_count
    if remaining_count:
        return None
    active_incidents = active_incidents_by_device.get(device_id, [])
    if not active_incidents:
        return None
    for active_incident in active_incidents:
        await incident_repository.resolve_incident(active_incident, resolved_at, commit=False)
    active_incidents_by_device.pop(device_id, None)
    return "resolved"


async def _resolve_orphan_incidents(
    incident_repository: IncidentRepository,
    active_incidents_by_device: dict[int | None, list[Incident]],
    active_alert_count_by_device: dict[int | None, int],
    resolved_at,
) -> list[dict]:
    """Resolve active incidents that no longer have any active alert rows."""
    notifications: list[dict] = []
    for device_id, active_incidents in list(active_incidents_by_device.items()):
        if active_alert_count_by_device.get(device_id, 0):
            continue
        for active_incident in active_incidents:
            await incident_repository.resolve_incident(active_incident, resolved_at, commit=False)
        active_incidents_by_device.pop(device_id, None)
        notifications.append(
            {
                "action": "resolved",
                "alert_type": None,
                "device_id": device_id,
                "message": "Incident cleared because no active alerts remain",
                "incident_action": "resolved",
            }
        )
    return notifications


async def _load_internet_service_history_by_device(
    metric_repository: MetricRepository,
    device_ids: list[int],
) -> dict[int, dict[str, list[Metric]]]:
    """Load bounded DNS/HTTP history used to debounce transient internet-service spikes."""
    if not device_ids:
        return {}
    history_by_device: dict[int, dict[str, list[Metric]]] = {}
    for metric_name in ("dns_resolution_time", "http_response_time"):
        metric_history = await metric_repository.list_recent_metrics_by_device(
            device_ids=device_ids,
            metric_name=metric_name,
            per_device_limit=2,
        )
        for device_id, metrics in metric_history.items():
            history_by_device.setdefault(device_id, {})[metric_name] = metrics
    return history_by_device
