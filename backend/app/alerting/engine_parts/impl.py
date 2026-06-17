"""Alert evaluation, incident transitions, and notification orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
from ...repositories.threshold_repository import ThresholdRepository
from ...services.threshold_service import get_threshold_runtime_config, threshold_for_device
from ..notifiers.telegram_notifier import send_telegram_alert
from ..rules import ALERT_RULES
from .constants import (
    ALERT_DYNAMIC_METRIC_NAME_PATTERNS,
    ALERT_EXACT_METRIC_NAMES,
    ALERT_PRIMARY_METRIC_BY_TYPE,
    TELEGRAM_NOTIFICATION_DEDUPE_TTL,  # noqa: F401 - re-exported by backend.app.alerting.engine
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


# Backward-compat shim for tests that still reference this symbol.
# Telegram dedupe is now stateless and batch-scoped.
_recent_telegram_notification_keys: dict[tuple, datetime] = {}
_DEFAULT_REALTIME_SEVERITIES = {"critical", "high", "warning"}


@dataclass
class AlertEvaluationState:
    """Mutable state that moves through alert-evaluation phases."""

    alerts: dict[tuple[int | None, str], Alert]
    alerts_count_by_device: dict[int | None, int]
    incidents_by_device: dict[int | None, list[Incident]]
    notifications: list[dict]
    telegram_events: list[dict]
    has_pending_writes: bool


@dataclass(frozen=True)
class TelegramNotificationPolicy:
    """Normalized Telegram alerting policy used by notification selection."""

    realtime_severities: set[str]
    summary_severities: set[str]
    alert_grace_period_seconds: int
    summary_interval_seconds: int
    notification_cooldown_seconds: int
    resolved_correlation_window_seconds: int


async def evaluate_alerts(db, *, commit: bool = True) -> list[dict]:
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
    threshold_config = await get_threshold_runtime_config(db, commit=commit)
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
    )
    notification_policy = _telegram_notification_policy()

    await _apply_created_alerts(state, expected_alerts, alert_repository, incident_repository)
    await _apply_resolved_alerts(
        state,
        expected_alerts,
        alert_repository,
        incident_repository,
        device_by_id=device_by_id,
        device_type_by_id=device_type_by_id,
        notification_policy=notification_policy,
    )
    await _resolve_orphans(state, incident_repository)
    await _flush_alert_state_changes(db, state, commit=commit)

    state.telegram_events.extend(
        _pending_active_telegram_events(
            state.alerts.values(),
            device_by_id=device_by_id,
            device_type_by_id=device_type_by_id,
            latest_metrics=latest_metrics,
            policy=notification_policy,
        )
    )
    await _send_telegram_events(
        db,
        alert_repository,
        _filter_recent_telegram_events(state.telegram_events),
        commit=commit,
    )
    return state.notifications


async def _load_alert_evaluation_inputs(
    *,
    metric_repository: MetricRepository,
    alert_repository: AlertRepository,
    device_repository: DeviceRepository,
) -> tuple[dict, list[Alert], list, dict[int, object], dict[int, str]]:
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
        state.alerts_count_by_device[created_alert.device_id] = state.alerts_count_by_device.get(created_alert.device_id, 0) + 1
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
    device_by_id: dict[int, object],
    device_type_by_id: dict[int, str],
    notification_policy: TelegramNotificationPolicy,
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


def _should_send_telegram_alert(alert_type: str, device_type: str | None) -> bool:
    """Return whether an alert state change should be sent to Telegram."""
    return alert_type not in TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE.get(str(device_type or ""), set())


def _should_send_telegram_resolved_alert(alert, resolved_at, device_type: str | None) -> bool:
    """Return whether a resolved alert should be sent to Telegram."""
    if not _should_send_telegram_alert(alert.alert_type, device_type):
        return False
    return alert.telegram_notified_at is not None


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


def _alert_reached_telegram_grace_period(
    started_at: datetime | None,
    current_time: datetime | None,
    *,
    grace_period_seconds: int | None = None,
) -> bool:
    """Return whether an alert has stayed active long enough for Telegram."""
    if started_at is None or current_time is None:
        return False
    grace_seconds = (
        max(int(grace_period_seconds), 0)
        if grace_period_seconds is not None
        else max(int(settings.telegram.alert_grace_period_seconds or 0), 0)
    )
    grace_period = timedelta(seconds=grace_seconds)
    return started_at <= current_time - grace_period


def _parse_severity_csv(raw_value: str, *, fallback: set[str] | None = None) -> set[str]:
    """Parse comma-separated severity names into a normalized set."""
    values = {item.strip().lower() for item in str(raw_value or "").split(",") if item.strip()}
    return values or set(fallback or set())


def _telegram_notification_cooldown(*, cooldown_seconds: int | None = None) -> timedelta:
    """Return minimum time between repeated sends for one active alert row."""
    seconds = (
        max(int(cooldown_seconds), 0)
        if cooldown_seconds is not None
        else max(int(settings.telegram.notification_cooldown_seconds or 0), 0)
    )
    return timedelta(seconds=seconds)


def _telegram_notification_policy() -> TelegramNotificationPolicy:
    """Build one normalized Telegram policy snapshot from runtime settings."""
    return TelegramNotificationPolicy(
        realtime_severities=_parse_severity_csv(
            settings.telegram.realtime_severities,
            fallback=_DEFAULT_REALTIME_SEVERITIES,
        ),
        summary_severities=_parse_severity_csv(settings.telegram.summary_severities),
        alert_grace_period_seconds=max(int(settings.telegram.alert_grace_period_seconds or 0), 0),
        summary_interval_seconds=max(int(settings.telegram.summary_interval_seconds or 0), 0),
        notification_cooldown_seconds=max(int(settings.telegram.notification_cooldown_seconds or 0), 0),
        resolved_correlation_window_seconds=max(int(settings.telegram.resolved_correlation_window_seconds or 0), 0),
    )


def _alert_reached_telegram_cooldown(
    last_notified_at: datetime | None,
    current_time: datetime | None,
    *,
    cooldown_seconds: int | None = None,
) -> bool:
    """Return whether cooldown has elapsed since the last Telegram send."""
    if last_notified_at is None or current_time is None:
        return True
    return last_notified_at <= current_time - _telegram_notification_cooldown(cooldown_seconds=cooldown_seconds)


def _alert_reached_summary_interval(
    started_at: datetime | None,
    current_time: datetime | None,
    *,
    summary_interval_seconds: int | None = None,
) -> bool:
    """Return whether an alert has aged long enough to be sent as summary."""
    if started_at is None or current_time is None:
        return False
    interval_seconds = (
        max(int(summary_interval_seconds), 0)
        if summary_interval_seconds is not None
        else max(int(settings.telegram.summary_interval_seconds or 0), 0)
    )
    if interval_seconds <= 0:
        return False
    return started_at <= current_time - timedelta(seconds=interval_seconds)


def _pending_active_telegram_events(
    alerts,
    *,
    device_by_id: dict,
    device_type_by_id: dict,
    latest_metrics: dict[tuple[int, str], Metric] | None = None,
    policy: TelegramNotificationPolicy | None = None,
) -> list[dict]:
    """Return active alerts ready for Telegram based on realtime and summary rules."""
    policy = policy or _telegram_notification_policy()
    current_time = utcnow()
    events: list[dict] = []
    for alert in alerts:
        device_type = device_type_by_id.get(alert.device_id) if alert.device_id is not None else None
        if not _should_send_telegram_alert(alert.alert_type, device_type):
            continue
        if _active_alert_metric_is_stale(alert, latest_metrics, current_time=current_time):
            continue
        alert_severity = str(alert.severity or "unknown").lower()
        should_send_realtime = (
            alert_severity in policy.realtime_severities
            and _alert_reached_telegram_grace_period(
                alert.created_at,
                current_time,
                grace_period_seconds=policy.alert_grace_period_seconds,
            )
            and alert.telegram_notified_at is None
        )
        should_send_summary = (
            alert_severity in policy.summary_severities
            and _alert_reached_summary_interval(
                alert.created_at,
                current_time,
                summary_interval_seconds=policy.summary_interval_seconds,
            )
            and alert.telegram_notified_at is None
        )
        if not should_send_realtime and not should_send_summary:
            continue
        action = "summary_active" if should_send_summary and not should_send_realtime else "active"
        events.append(
            {
                "action": action,
                "alert": alert,
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "device": device_by_id.get(alert.device_id),
            }
        )
    return events


def _active_alert_metric_is_stale(
    alert,
    latest_metrics: dict[tuple[int, str], Metric] | None,
    *,
    current_time: datetime,
) -> bool:
    """Avoid Telegram ACTIVE noise for alerts backed only by stale latest metrics."""
    if latest_metrics is None or alert.device_id is None:
        return False

    metric_name = ALERT_PRIMARY_METRIC_BY_TYPE.get(str(alert.alert_type or ""))
    if not metric_name:
        return False

    metric = latest_metrics.get((alert.device_id, metric_name))
    if metric is None:
        return True

    return _metric_is_stale(
        metric,
        current_time=current_time,
        stale_after_seconds=_alert_metric_stale_after_seconds(),
    )


def _metric_is_stale(metric, *, current_time: datetime, stale_after_seconds: int) -> bool:
    """Return whether a metric snapshot is older than the alert freshness window."""
    checked_at = getattr(metric, "checked_at", None)
    if checked_at is None:
        return True
    return checked_at <= current_time - timedelta(seconds=stale_after_seconds)


def _alert_metric_stale_after_seconds() -> int:
    """Return alert freshness window based on scheduler cadence."""
    return max(
        int(settings.scheduler.interval_device_seconds) * max(int(settings.scheduler.job_stale_factor), 1),
        60,
    )


def _filter_recent_telegram_events(events: list[dict]) -> list[dict]:
    """Suppress duplicate Telegram events within a single send batch."""
    if not events:
        return []
    seen_keys: set[tuple] = set()
    filtered_events: list[dict] = []
    for event in events:
        notification_key = _telegram_notification_key(event)
        if notification_key in seen_keys:
            continue
        seen_keys.add(notification_key)
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
    action_rank = {"active": 0, "summary_active": 1, "created": 1, "resolved": 2}
    return sorted(events, key=lambda event: action_rank.get(str(event.get("action") or "active").lower(), 0))


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
        if isinstance(result, Exception):
            continue
        for event in group:
            alert = event.get("alert")
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
            if str(event.get("action") or "active").lower() not in {"active", "summary_active"}:
                continue
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
        if action not in {"active", "summary_active"}:
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
    is_summary = str(action or "").lower() == "summary_active"
    title = "ALERT RESOLVED" if is_resolved else ("ALERT SUMMARY" if is_summary else "ALERT ACTIVE")
    status = "RESOLVED" if is_resolved else ("SUMMARY" if is_summary else "ACTIVE")
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
