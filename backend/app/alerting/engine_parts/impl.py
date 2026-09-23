"""Alert evaluation, incident transitions, and notification orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Mapping
from datetime import datetime, timedelta

from ...core.config import settings as settings
from ...core.time import utcnow
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from ...models.alert import Alert
from ...models.incident import Incident
from ...models.metric import Metric
from ...models.device import Device
from ...services.dashboard_overview_service import invalidate_dashboard_overview_cache
from ...repositories.threshold_repository import ThresholdRepository
from ...services.threshold_service import get_threshold_runtime_config, threshold_for_device
from ..notifiers.telegram_notifier import send_telegram_alert
from ..rules import ALERT_RULES
from ..notification_contracts import NotificationBatchWriter
from ...services.alert_notification_outbox_service import pending_active_notification_ids, lock_alert_notification_state
from .constants import (
    ALERT_DYNAMIC_METRIC_NAME_PATTERNS,
    ALERT_EXACT_METRIC_NAMES,
    TELEGRAM_NOTIFICATION_DEDUPE_TTL,  # noqa: F401 - re-exported by backend.app.alerting.engine
    TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE as TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE,
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

# Explicit re-exports preserve the existing engine facade during migration.
from .notification_policy import (
    TelegramNotificationPolicy as TelegramNotificationPolicy,
    _should_send_telegram_alert as _should_send_telegram_alert,
    _should_send_telegram_resolved_alert as _should_send_telegram_resolved_alert,
    _alert_reached_telegram_grace_period as _alert_reached_telegram_grace_period,
    _parse_severity_csv as _parse_severity_csv,
    _telegram_notification_cooldown as _telegram_notification_cooldown,
    _telegram_notification_policy as _telegram_notification_policy,
    _parse_alert_type_csv as _parse_alert_type_csv,
    _alert_reached_telegram_cooldown as _alert_reached_telegram_cooldown,
    _alert_reached_summary_interval as _alert_reached_summary_interval,
    _pending_active_telegram_events as _pending_active_telegram_events,
    _collapse_site_outage_events as _collapse_site_outage_events,
    _telegram_realtime_device_allowed as _telegram_realtime_device_allowed,
    _telegram_summary_allowed as _telegram_summary_allowed,
    _alert_reached_summary_delivery_threshold as _alert_reached_summary_delivery_threshold,
    _alert_passes_flap_suppression as _alert_passes_flap_suppression,
    _telegram_alert_grace_period_seconds as _telegram_alert_grace_period_seconds,
    _active_telegram_cooldown_seconds as _active_telegram_cooldown_seconds,
    _telegram_active_event_action as _telegram_active_event_action,
    _alert_reached_telegram_summary_threshold as _alert_reached_telegram_summary_threshold,
    _active_alert_metric_is_stale as _active_alert_metric_is_stale,
    _metric_is_stale as _metric_is_stale,
    _alert_metric_stale_after_seconds as _alert_metric_stale_after_seconds,
)
from .notification_formatting import (
    _filter_recent_telegram_events as _filter_recent_telegram_events,
    _telegram_notification_key as _telegram_notification_key,
    _build_telegram_messages as _build_telegram_messages,
    _group_telegram_events as _group_telegram_events,
    _order_telegram_events as _order_telegram_events,
    _build_telegram_message as _build_telegram_message,
    _build_batched_telegram_message as _build_batched_telegram_message,
    _format_batched_telegram_alert_line as _format_batched_telegram_alert_line,
    _format_telegram_alert_line as _format_telegram_alert_line,
    _format_telegram_summary_alert_lines as _format_telegram_summary_alert_lines,
    _summary_alerts_for_events as _summary_alerts_for_events,
    _format_degraded_summary_line as _format_degraded_summary_line,
    _max_metric_ms as _max_metric_ms,
    _format_metric_latency as _format_metric_latency,
    _format_summary_window as _format_summary_window,
    _format_alert_duration as _format_alert_duration,
    _highest_severity as _highest_severity,
)
from .notification_policy import _SUMMARY_AGGREGATE_ALERT_TYPES


# Backward-compat shim for tests that still reference this symbol.
# Telegram dedupe is now stateless and batch-scoped.
_recent_telegram_notification_keys: dict[tuple, datetime] = {}


@dataclass
class AlertEvaluationState:
    """Mutable state that moves through alert-evaluation phases."""

    alerts: dict[tuple[int | None, str], Alert]
    alerts_count_by_device: dict[int | None, int]
    incidents_by_device: dict[int | None, list[Incident]]
    notifications: list[dict]
    telegram_events: list[dict]
    has_pending_writes: bool


async def evaluate_alerts(
    db, *, commit: bool = True, notification_writer: NotificationBatchWriter | None = None
) -> list[dict]:
    """Evaluate latest metrics, create or resolve alerts, maintain incidents, and queue notifications."""
    alert_repository = AlertRepository(db)
    incident_repository = IncidentRepository(db)
    metric_repository = MetricRepository(db)
    device_repository = DeviceRepository(db)

    latest_metrics, active_alerts_list, devices, device_by_id, device_type_by_id = await _load_alert_evaluation_inputs(
        metric_repository=metric_repository,
        alert_repository=alert_repository,
        device_repository=device_repository,
    )
    # Outbox mode keeps every domain write in the same transaction as enqueue,
    # including threshold defaults that may be created during configuration load.
    domain_commit = commit and notification_writer is None
    if notification_writer is not None:
        # Acquire all existing alert rows before incident transitions/stream jobs;
        # delivery acknowledgements follow the same domain-before-job ordering.
        await lock_alert_notification_state(db, {alert.id for alert in active_alerts_list})
    threshold_config = await get_threshold_runtime_config(db, commit=domain_commit)
    thresholds = threshold_config["thresholds"]
    threshold_overrides = threshold_config["overrides"]
    active_maintenance_windows = await _load_active_maintenance_windows(db, devices)
    state = await _build_alert_evaluation_state(
        incident_repository=incident_repository,
        active_alerts=active_alerts_list,
        candidate_device_ids={device.id for device in devices},
    )
    expected_alerts = await _expected_alert_map(
        metric_repository=metric_repository,
        devices=devices,
        latest_metrics=latest_metrics,
        thresholds=thresholds,
        threshold_overrides=threshold_overrides,
        active_maintenance_windows=active_maintenance_windows,
        active_alerts=active_alerts_list,
    )
    notification_policy = _telegram_notification_policy()
    queued_active_ids = (
        await pending_active_notification_ids(db, {alert.id for alert in active_alerts_list})
        if notification_writer is not None
        else set()
    )

    await _apply_created_alerts(state, expected_alerts, alert_repository, incident_repository)
    await _apply_resolved_alerts(
        state,
        expected_alerts,
        alert_repository,
        incident_repository,
        device_by_id=device_by_id,
        device_type_by_id=device_type_by_id,
        notification_policy=notification_policy,
        queued_active_ids=queued_active_ids,
    )
    await _resolve_orphans(state, incident_repository)
    await _flush_alert_state_changes(db, state, commit=domain_commit)

    state.telegram_events.extend(
        _pending_active_telegram_events(
            [alert for alert in state.alerts.values() if alert.id not in queued_active_ids],
            device_by_id=device_by_id,
            device_type_by_id=device_type_by_id,
            latest_metrics=latest_metrics,
            policy=notification_policy,
            recent_alert_counts=await _recent_telegram_policy_counts(
                alert_repository,
                state.alerts.values(),
                policy=notification_policy,
            ),
            recent_summary_alerts=await _recent_telegram_summary_alerts(
                alert_repository,
                state.alerts.values(),
                policy=notification_policy,
            ),
            recently_notified_keys=await _recent_telegram_notified_keys(
                alert_repository, state.alerts.values(), policy=notification_policy
            ),
        )
    )
    events = _filter_recent_telegram_events(state.telegram_events)
    if notification_writer is None:
        await _send_telegram_events(db, alert_repository, events, commit=commit)
    else:
        await notification_writer(db, _order_telegram_events(await _refresh_telegram_events(db, events)))
        if commit:
            await db.commit()
        else:
            await db.flush()
    return state.notifications


async def _load_alert_evaluation_inputs(
    *,
    metric_repository: MetricRepository,
    alert_repository: AlertRepository,
    device_repository: DeviceRepository,
) -> tuple[dict[tuple[int, str], Metric], list[Alert], list[Device], dict[int, Device], dict[int, str]]:
    """Load bounded metric/device/alert snapshots required for one evaluation cycle."""
    latest_metrics = await metric_repository.latest_metric_map_for_alert_evaluation(
        exact_metric_names=ALERT_EXACT_METRIC_NAMES,
        dynamic_metric_name_patterns=ALERT_DYNAMIC_METRIC_NAME_PATTERNS,
    )
    latest_metrics = _drop_stale_dynamic_alert_metrics(latest_metrics)
    active_alerts_list = await alert_repository.list_active_alerts_by_types(set(ALERT_RULES))
    active_alert_device_ids = {alert.device_id for alert in active_alerts_list if alert.device_id is not None}
    latest_metric_device_ids = {device_id for device_id, _metric_name in latest_metrics}
    candidate_device_ids = latest_metric_device_ids | active_alert_device_ids
    devices = await device_repository.list_devices_by_ids(candidate_device_ids, active_only=True)
    device_by_id = {device.id: device for device in devices}
    device_type_by_id = {device.id: device.device_type for device in devices}
    return latest_metrics, active_alerts_list, devices, device_by_id, device_type_by_id


def _drop_stale_dynamic_alert_metrics(latest_metrics: dict[tuple[int, str], Metric]) -> dict[tuple[int, str], Metric]:
    """Remove stale dynamic metric snapshots so renamed/removed objects do not keep alerts active."""
    if not latest_metrics:
        return latest_metrics

    current_time = utcnow()
    stale_after_seconds = _alert_metric_stale_after_seconds()
    filtered_metrics = {}
    for key, metric in latest_metrics.items():
        _device_id, metric_name = key
        if _is_dynamic_alert_metric_name(metric_name) and _metric_is_stale(
            metric,
            current_time=current_time,
            stale_after_seconds=stale_after_seconds,
        ):
            continue
        filtered_metrics[key] = metric
    return filtered_metrics


def _is_dynamic_alert_metric_name(metric_name: str) -> bool:
    """Return whether a metric name belongs to an alert dynamic-object pattern."""
    metric_name = str(metric_name or "")
    for pattern in ALERT_DYNAMIC_METRIC_NAME_PATTERNS:
        prefix, suffix = pattern.split("%", 1)
        if metric_name.startswith(prefix) and metric_name.endswith(suffix):
            return True
    return False


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


async def _expected_alert_map(
    *,
    metric_repository: MetricRepository,
    devices: list,
    latest_metrics: dict,
    thresholds: dict,
    threshold_overrides: list[dict],
    active_maintenance_windows: list,
    active_alerts: list[Alert],
) -> dict[tuple[int | None, str], dict]:
    """Evaluate all device rules and return expected active alerts."""
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
    metric_history_by_device = await _load_rolling_metric_history_by_device(
        metric_repository,
        [device.id for device in devices],
        latest_metrics=latest_metrics,
    )

    expected_alerts: dict[tuple[int | None, str], dict] = {}
    for device in devices:
        if _device_in_maintenance(device, active_maintenance_windows):
            continue
        device_thresholds = _effective_thresholds_for_device(thresholds, threshold_overrides, device)
        evaluate_expected_alerts_for_device(
            AlertEvaluationContext(
                device=device,
                latest_metrics=latest_metrics,
                thresholds=device_thresholds,
                threshold_overrides=threshold_overrides,
                expected_alerts=expected_alerts,
                printer_uptime_history_by_device=printer_uptime_history_by_device,
                internet_service_history_by_device=internet_service_history_by_device,
                metric_history_by_device=metric_history_by_device,
            )
        )
    # Require three successful ping samples before resolving a reachability alert.
    # This prevents a one-cycle recovery from reopening Telegram noise during flaps.
    for alert in active_alerts:
        key = (alert.device_id, alert.alert_type)
        if alert.alert_type not in {"device_down", "internet_loss"} or key in expected_alerts:
            continue
        history = (
            metric_history_by_device.get(alert.device_id, {}).get("ping", []) if alert.device_id is not None else []
        )
        if len(history) < 3 or any(str(metric.status or "").lower() == "down" for metric in history[:3]):
            expected_alerts[key] = {
                "device_id": alert.device_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
            }
    return expected_alerts


async def _apply_created_alerts(
    state: AlertEvaluationState,
    expected_alerts: dict[tuple[int | None, str], dict],
    alert_repository: AlertRepository,
    incident_repository: IncidentRepository,
) -> None:
    """Create alert rows for newly-triggered conditions."""
    for key, payload in expected_alerts.items():
        if key in state.alerts:
            continue
        created_alert = await alert_repository.create_alert(payload, commit=False)
        state.alerts[key] = created_alert
        state.alerts_count_by_device[created_alert.device_id] = (
            state.alerts_count_by_device.get(created_alert.device_id, 0) + 1
        )
        incident_action = await _ensure_incident_for_alert(
            incident_repository,
            state.incidents_by_device,
            created_alert.device_id,
            created_alert.message,
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
) -> None:
    """Resolve active alerts no longer expected from the latest metrics."""
    resolved_at = utcnow()
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


async def _resolve_orphans(state: AlertEvaluationState, incident_repository: IncidentRepository) -> None:
    """Resolve orphan incidents that no longer have active alerts."""
    orphan_incident_actions = await _resolve_orphan_incidents(
        incident_repository,
        state.incidents_by_device,
        state.alerts_count_by_device,
        utcnow(),
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


async def _resolved_alert_recently_notified(
    alert_repository: AlertRepository,
    *,
    alert,
    resolved_at: datetime,
    policy: TelegramNotificationPolicy,
) -> bool:
    """Return whether a sibling alert was recently notified for the same device and alert type."""
    # Covers short-lived duplicate rows created during flapping so RESOLVED
    # remains visible when ACTIVE for the same logical issue was already sent.
    lookback_seconds = max(int(policy.resolved_correlation_window_seconds or 0), 0)
    return await alert_repository.has_recent_telegram_notified_alert(
        device_id=alert.device_id,
        alert_type=alert.alert_type,
        since=resolved_at - timedelta(seconds=lookback_seconds),
    )


async def _recent_telegram_policy_counts(
    alert_repository: AlertRepository,
    alerts,
    *,
    policy: TelegramNotificationPolicy,
) -> dict[tuple[int | None, str], int]:
    """Return recent repeat counts for summary and flap suppression policies."""
    lookback_seconds = max(policy.summary_repeat_window_seconds, policy.flap_repeat_window_seconds)
    if lookback_seconds <= 0:
        return {}
    keys = {
        (alert.device_id, str(alert.alert_type or "").lower())
        for alert in alerts
        if str(alert.alert_type or "").lower() in policy.summary_alert_types
        or str(alert.alert_type or "").lower() == "high_packet_loss_critical"
        or str(alert.alert_type or "").lower() == "device_down"
    }
    return await alert_repository.count_recent_alerts_by_key(
        keys,
        since=utcnow() - timedelta(seconds=lookback_seconds),
    )


async def _recent_telegram_summary_alerts(
    alert_repository: AlertRepository,
    alerts,
    *,
    policy: TelegramNotificationPolicy,
) -> dict[int | None, list[Alert]]:
    """Return recent alert rows used to aggregate Telegram summary messages."""
    if policy.summary_repeat_window_seconds <= 0:
        return {}
    keys = {
        (alert.device_id, str(alert.alert_type or "").lower())
        for alert in alerts
        if str(alert.alert_type or "").lower() in _SUMMARY_AGGREGATE_ALERT_TYPES
    }
    return await alert_repository.list_recent_alerts_by_keys(
        keys,
        since=utcnow() - timedelta(seconds=policy.summary_repeat_window_seconds),
    )


async def _recent_telegram_notified_keys(
    alert_repository: AlertRepository, alerts, *, policy: TelegramNotificationPolicy
) -> set[tuple[int | None, str]]:
    """Keep cooldown after a flap creates a replacement alert row."""
    if policy.notification_cooldown_seconds <= 0:
        return set()
    keys = {(alert.device_id, str(alert.alert_type or "").lower()) for alert in alerts}
    return await alert_repository.recent_telegram_notified_keys(
        keys, since=utcnow() - timedelta(seconds=policy.notification_cooldown_seconds)
    )


async def _send_telegram_events(db, alert_repository: AlertRepository, events: list[dict], *, commit: bool) -> None:
    """Send Telegram events and mark active alerts that were successfully delivered."""
    incident_repository = IncidentRepository(db)
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
    has_notification_events = False
    for group, result in zip(grouped_items, results, strict=True):
        # ``None`` remains accepted for legacy test notifiers; the real notifier
        # returns False when Telegram was skipped or rejected the request.
        if isinstance(result, Exception) or result is False:
            continue
        for event in group:
            event_alerts = event.get("alerts") or [event.get("alert")]
            for alert in event_alerts:
                if alert is None:
                    continue
                await incident_repository.add_notification_timeline_event_for_alert(
                    alert=alert,
                    action=str(event.get("action") or "active"),
                    channel="telegram",
                    notified_at=notified_at,
                    commit=False,
                )
                has_notification_events = True
                if str(event.get("action") or "active").lower() in {"active", "active_reminder", "summary_active"}:
                    await alert_repository.mark_telegram_notified(alert, notified_at, commit=False)
                    has_marked_alerts = True

    if has_marked_alerts or has_notification_events:
        if commit:
            await db.commit()
        else:
            await db.flush()


async def _refresh_telegram_events(db, events: list[dict]) -> list[dict]:
    """Re-read active events before sending so stale ACTIVE messages do not outlive resolved alerts."""
    refreshed_events: list[dict] = []
    for event in events:
        action = str(event.get("action") or "active").lower()
        if action not in {"active", "active_reminder", "summary_active"}:
            refreshed_events.append(event)
            continue

        alert_id = event.get("alert_id")
        if alert_id is None:
            refreshed_events.append(event)
            continue

        fresh_alert = await db.get(Alert, alert_id)
        if fresh_alert is None:
            continue
        if fresh_alert.telegram_notified_at is not None and action != "active_reminder":
            continue
        fresh_event = {**event, "alert": fresh_alert}
        if str(fresh_alert.status or "").lower() == "active":
            refreshed_events.append(fresh_event)
            continue
        if str(fresh_alert.status or "").lower() == "resolved":
            continue
    return refreshed_events


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


async def _load_rolling_metric_history_by_device(
    metric_repository: MetricRepository,
    device_ids: list[int],
    *,
    latest_metrics: dict,
) -> dict[int, dict[str, list[Metric]]]:
    """Load recent metric windows used by rolling alert rules."""
    if not device_ids:
        return {}
    history_by_device: dict[int, dict[str, list[Metric]]] = {}
    metric_names = {"ping", "packet_loss", "jitter"}
    metric_names.update(
        metric_name
        for _device_id, metric_name in latest_metrics
        if str(metric_name).startswith("interface:") and str(metric_name).endswith("_mbps")
    )
    for metric_name in sorted(metric_names):
        metric_history = await metric_repository.list_recent_metrics_by_device(
            device_ids=device_ids,
            metric_name=metric_name,
            per_device_limit=5,
        )
        for device_id, metrics in metric_history.items():
            history_by_device.setdefault(device_id, {})[metric_name] = metrics
    return history_by_device


async def _load_active_maintenance_windows(db, devices: list) -> list:
    """Load active maintenance windows that match candidate device/site scopes."""
    device_ids = {device.id for device in devices if device.id is not None}
    sites = {str(device.site).strip() for device in devices if str(device.site or "").strip()}
    return await ThresholdRepository(db).active_maintenance_windows_for_devices(device_ids=device_ids, sites=sites)


def _device_in_maintenance(device, windows: list) -> bool:
    """Return whether a device is currently covered by a maintenance window."""
    for window in windows:
        if window.device_id is not None and window.device_id == device.id:
            return True
        if window.site and str(window.site).strip().lower() == str(device.site or "").strip().lower():
            return True
    return False


def _effective_thresholds_for_device(thresholds: dict[str, float], overrides: list[dict], device) -> dict[str, float]:
    """Return threshold map with scoped overrides applied for one device."""
    effective = dict(thresholds)
    for key in list(thresholds):
        effective[key] = threshold_for_device(thresholds, overrides, device, key)
    return effective
