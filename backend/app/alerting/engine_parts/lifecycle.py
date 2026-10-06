"""Lifecycle: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from ...core.time import utcnow
from ...models.alert import Alert
from ...models.incident import Incident
from ...repositories.alert_repository import AlertRepository
from ...repositories.incident_repository import IncidentRepository
from ...services.dashboard_overview_service import invalidate_dashboard_overview_cache
from .notification_policy import TelegramNotificationPolicy as TelegramNotificationPolicy
from .notification_policy import _should_send_telegram_alert as _should_send_telegram_alert
from .notification_policy import _should_send_telegram_resolved_alert as _should_send_telegram_resolved_alert
from .notification_queries import _resolved_alert_recently_notified


@dataclass
class AlertEvaluationState:
    """Mutable state that moves through alert-evaluation phases."""

    alerts: dict[tuple[int | None, str], Alert]
    alerts_count_by_device: dict[int | None, int]
    incidents_by_device: dict[int | None, list[Incident]]
    notifications: list[dict]
    telegram_events: list[dict]
    has_pending_writes: bool


async def _build_alert_evaluation_state(
    *,
    incident_repository: IncidentRepository,
    active_alerts: list[Alert],
    candidate_device_ids: set[int],
) -> AlertEvaluationState:
    """Build mutable evaluation state from active alerts and incidents."""
    alerts = {(alert.device_id, alert.alert_type): alert for alert in active_alerts}
    alerts_count_by_device: dict[int | None, int] = {}
    for alert in alerts.values():
        alerts_count_by_device[alert.device_id] = alerts_count_by_device.get(alert.device_id, 0) + 1

    active_incident_device_ids: set[int | None] = set(candidate_device_ids)
    active_incident_device_ids.update(device_id for device_id in alerts_count_by_device if device_id is not None)
    incidents_by_device = _group_incidents_by_device(
        await incident_repository.list_active_incidents_by_device_ids(active_incident_device_ids)
    )
    return AlertEvaluationState(
        alerts=alerts,
        alerts_count_by_device=alerts_count_by_device,
        incidents_by_device=incidents_by_device,
        notifications=[],
        telegram_events=[],
        has_pending_writes=False,
    )


async def _apply_created_alerts(
    state: AlertEvaluationState,
    expected_alerts: dict[tuple[int | None, str], dict],
    alert_repository: AlertRepository,
    incident_repository: IncidentRepository,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> None:
    """Create alert rows for newly-triggered conditions."""
    for key, payload in expected_alerts.items():
        if key in state.alerts:
            continue
        created_alert = await alert_repository.create_alert({**payload, "created_at": clock()}, commit=False)
        state.alerts[key] = created_alert
        state.alerts_count_by_device[created_alert.device_id] = (
            state.alerts_count_by_device.get(created_alert.device_id, 0) + 1
        )
        incident_action = await _ensure_incident_for_alert(
            incident_repository,
            state.incidents_by_device,
            created_alert.device_id,
            created_alert.message,
            clock=clock,
        )
        await incident_repository.add_alert_timeline_event(
            device_id=created_alert.device_id,
            alert_type=created_alert.alert_type,
            message=created_alert.message,
            action="created",
            event_at=created_alert.created_at,
            commit=False,
        )
        state.has_pending_writes = True
        state.notifications.append(
            {
                "action": "created",
                "alert_type": created_alert.alert_type,
                "device_id": created_alert.device_id,
                "message": created_alert.message,
                "incident_action": incident_action,
            }
        )


async def _apply_resolved_alerts(
    state: AlertEvaluationState,
    expected_alerts: dict[tuple[int | None, str], dict],
    alert_repository: AlertRepository,
    incident_repository: IncidentRepository,
    *,
    device_by_id: Mapping[int, object],
    device_type_by_id: dict[int, str],
    notification_policy: TelegramNotificationPolicy,
    queued_active_ids: set[int] | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> None:
    """Resolve active alerts no longer expected from the latest metrics."""
    resolved_at = clock()
    for key, alert in list(state.alerts.items()):
        if key in expected_alerts:
            continue
        await alert_repository.resolve_alert(alert, resolved_at, commit=False)
        incident_action = await _resolve_incident_if_cleared(
            incident_repository,
            state.incidents_by_device,
            state.alerts_count_by_device,
            alert.device_id,
            resolved_at,
        )
        await incident_repository.add_alert_timeline_event(
            device_id=alert.device_id,
            alert_type=alert.alert_type,
            message=alert.message,
            action="resolved",
            event_at=resolved_at,
            commit=False,
        )
        state.has_pending_writes = True
        state.alerts.pop(key, None)
        resolved_alert_device_type = device_type_by_id.get(alert.device_id) if alert.device_id is not None else None
        state.notifications.append(
            {
                "action": "resolved",
                "alert_type": alert.alert_type,
                "device_id": alert.device_id,
                "message": alert.message,
                "incident_action": incident_action,
            }
        )
        should_send_resolved = _should_send_telegram_resolved_alert(alert, resolved_at, resolved_alert_device_type)
        if alert.id in (queued_active_ids or set()) and _should_send_telegram_alert(
            alert.alert_type, resolved_alert_device_type
        ):
            should_send_resolved = True
        if not should_send_resolved:
            should_send_resolved = await _resolved_alert_recently_notified(
                alert_repository,
                alert=alert,
                resolved_at=resolved_at,
                policy=notification_policy,
            )
        if should_send_resolved:
            state.telegram_events.append(
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


async def _resolve_orphans(
    state: AlertEvaluationState, incident_repository: IncidentRepository, *, clock: Callable[[], datetime] = utcnow
) -> None:
    """Resolve orphan incidents that no longer have active alerts."""
    orphan_incident_actions = await _resolve_orphan_incidents(
        incident_repository,
        state.incidents_by_device,
        state.alerts_count_by_device,
        clock(),
    )
    if orphan_incident_actions:
        state.has_pending_writes = True
        state.notifications.extend(orphan_incident_actions)


async def _flush_alert_state_changes(db, state: AlertEvaluationState, *, commit: bool) -> None:
    """Persist pending alert/incident changes and invalidate dashboard cache."""
    if not state.has_pending_writes:
        return
    if commit:
        await db.commit()
    else:
        await db.flush()
    invalidate_dashboard_overview_cache()


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
    *,
    clock: Callable[[], datetime] = utcnow,
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
            "started_at": clock(),
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
