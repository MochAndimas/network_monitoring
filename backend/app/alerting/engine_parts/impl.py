"""Alert evaluation, incident transitions, and notification orchestration."""

from __future__ import annotations

from datetime import datetime

from ...core.config import settings as settings
from ...services.alert_notification_outbox_service import lock_alert_notification_state, pending_active_notification_ids
from ...services.threshold_service import get_threshold_runtime_config
from ..notification_contracts import NotificationBatchWriter
from ..notifiers.telegram_notifier import send_telegram_alert as send_telegram_alert
from .constants import (
    TELEGRAM_NOTIFICATION_DEDUPE_TTL,  # noqa: F401 - re-exported by backend.app.alerting.engine
)
from .constants import (
    TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE as TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE,
)
from .dependencies import AlertEvaluationDependencies, LegacySender
from .device_evaluators import _evaluate_mikrotik_alerts as _evaluate_mikrotik_alerts
from .device_evaluators import _evaluate_nas_alerts as _evaluate_nas_alerts
from .evaluation_inputs import _device_in_maintenance as _device_in_maintenance
from .evaluation_inputs import _drop_stale_dynamic_alert_metrics as _drop_stale_dynamic_alert_metrics
from .evaluation_inputs import _effective_thresholds_for_device as _effective_thresholds_for_device
from .evaluation_inputs import _expected_alert_map as _expected_alert_map
from .evaluation_inputs import _is_dynamic_alert_metric_name as _is_dynamic_alert_metric_name
from .evaluation_inputs import _load_active_maintenance_windows as _load_active_maintenance_windows
from .evaluation_inputs import _load_alert_evaluation_inputs as _load_alert_evaluation_inputs
from .evaluation_inputs import _load_internet_service_history_by_device as _load_internet_service_history_by_device
from .evaluation_inputs import _load_rolling_metric_history_by_device as _load_rolling_metric_history_by_device
from .legacy_delivery import _refresh_telegram_events as _refresh_telegram_events
from .legacy_delivery import _send_telegram_events as _send_telegram_events
from .lifecycle import AlertEvaluationState as AlertEvaluationState
from .lifecycle import _apply_created_alerts as _apply_created_alerts
from .lifecycle import _apply_resolved_alerts as _apply_resolved_alerts
from .lifecycle import _build_alert_evaluation_state as _build_alert_evaluation_state
from .lifecycle import _ensure_incident_for_alert as _ensure_incident_for_alert
from .lifecycle import _flush_alert_state_changes as _flush_alert_state_changes
from .lifecycle import _group_incidents_by_device as _group_incidents_by_device
from .lifecycle import _resolve_incident_if_cleared as _resolve_incident_if_cleared
from .lifecycle import _resolve_orphan_incidents as _resolve_orphan_incidents
from .lifecycle import _resolve_orphans as _resolve_orphans
from .notification_formatting import (
    _build_batched_telegram_message as _build_batched_telegram_message,
)
from .notification_formatting import (
    _build_telegram_message as _build_telegram_message,
)
from .notification_formatting import (
    _build_telegram_messages as _build_telegram_messages,
)
from .notification_formatting import (
    _filter_recent_telegram_events as _filter_recent_telegram_events,
)
from .notification_formatting import (
    _format_alert_duration as _format_alert_duration,
)
from .notification_formatting import (
    _format_batched_telegram_alert_line as _format_batched_telegram_alert_line,
)
from .notification_formatting import (
    _format_degraded_summary_line as _format_degraded_summary_line,
)
from .notification_formatting import (
    _format_metric_latency as _format_metric_latency,
)
from .notification_formatting import (
    _format_summary_window as _format_summary_window,
)
from .notification_formatting import (
    _format_telegram_alert_line as _format_telegram_alert_line,
)
from .notification_formatting import (
    _format_telegram_summary_alert_lines as _format_telegram_summary_alert_lines,
)
from .notification_formatting import (
    _group_telegram_events as _group_telegram_events,
)
from .notification_formatting import (
    _highest_severity as _highest_severity,
)
from .notification_formatting import (
    _max_metric_ms as _max_metric_ms,
)
from .notification_formatting import (
    _order_telegram_events as _order_telegram_events,
)
from .notification_formatting import (
    _summary_alerts_for_events as _summary_alerts_for_events,
)
from .notification_formatting import (
    _telegram_notification_key as _telegram_notification_key,
)

# Explicit re-exports preserve the existing engine facade during migration.
from .notification_policy import (
    TelegramNotificationPolicy as TelegramNotificationPolicy,
)
from .notification_policy import (
    _active_alert_metric_is_stale as _active_alert_metric_is_stale,
)
from .notification_policy import (
    _active_telegram_cooldown_seconds as _active_telegram_cooldown_seconds,
)
from .notification_policy import (
    _alert_metric_stale_after_seconds as _alert_metric_stale_after_seconds,
)
from .notification_policy import (
    _alert_passes_flap_suppression as _alert_passes_flap_suppression,
)
from .notification_policy import (
    _alert_reached_summary_delivery_threshold as _alert_reached_summary_delivery_threshold,
)
from .notification_policy import (
    _alert_reached_summary_interval as _alert_reached_summary_interval,
)
from .notification_policy import (
    _alert_reached_telegram_cooldown as _alert_reached_telegram_cooldown,
)
from .notification_policy import (
    _alert_reached_telegram_grace_period as _alert_reached_telegram_grace_period,
)
from .notification_policy import (
    _alert_reached_telegram_summary_threshold as _alert_reached_telegram_summary_threshold,
)
from .notification_policy import (
    _collapse_site_outage_events as _collapse_site_outage_events,
)
from .notification_policy import (
    _metric_is_stale as _metric_is_stale,
)
from .notification_policy import (
    _parse_alert_type_csv as _parse_alert_type_csv,
)
from .notification_policy import (
    _parse_severity_csv as _parse_severity_csv,
)
from .notification_policy import (
    _pending_active_telegram_events as _pending_active_telegram_events,
)
from .notification_policy import (
    _should_send_telegram_alert as _should_send_telegram_alert,
)
from .notification_policy import (
    _should_send_telegram_resolved_alert as _should_send_telegram_resolved_alert,
)
from .notification_policy import (
    _telegram_active_event_action as _telegram_active_event_action,
)
from .notification_policy import (
    _telegram_alert_grace_period_seconds as _telegram_alert_grace_period_seconds,
)
from .notification_policy import (
    _telegram_notification_cooldown as _telegram_notification_cooldown,
)
from .notification_policy import (
    _telegram_notification_policy as _telegram_notification_policy,
)
from .notification_policy import (
    _telegram_realtime_device_allowed as _telegram_realtime_device_allowed,
)
from .notification_policy import (
    _telegram_summary_allowed as _telegram_summary_allowed,
)
from .notification_queries import _recent_telegram_notified_keys as _recent_telegram_notified_keys
from .notification_queries import _recent_telegram_policy_counts as _recent_telegram_policy_counts
from .notification_queries import _recent_telegram_summary_alerts as _recent_telegram_summary_alerts
from .notification_queries import _resolved_alert_recently_notified as _resolved_alert_recently_notified
from .utils import (
    _build_alert_payload as _build_alert_payload,
)
from .utils import (
    _highest_dynamic_metric as _highest_dynamic_metric,
)
from .utils import (
    _metric_numeric_value as _metric_numeric_value,
)
from .utils import (
    _threshold_for_device as _threshold_for_device,
)

# Backward-compat shim for tests that still reference this symbol.
# Telegram dedupe is now stateless and batch-scoped.
_recent_telegram_notification_keys: dict[tuple, datetime] = {}


async def evaluate_alerts(
    db,
    *,
    commit: bool = True,
    notification_writer: NotificationBatchWriter | None = None,
    dependencies: AlertEvaluationDependencies | None = None,
    legacy_sender: LegacySender | None = None,
) -> list[dict]:
    """Evaluate latest metrics, create or resolve alerts, maintain incidents, and queue notifications."""
    dependencies = dependencies or AlertEvaluationDependencies()
    alert_repository = dependencies.alert_repository(db)
    incident_repository = dependencies.incident_repository(db)
    metric_repository = dependencies.metric_repository(db)
    device_repository = dependencies.device_repository(db)

    latest_metrics, active_alerts_list, devices, device_by_id, device_type_by_id = await _load_alert_evaluation_inputs(
        metric_repository=metric_repository,
        alert_repository=alert_repository,
        device_repository=device_repository,
        current_time=dependencies.clock(),
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
    expected_alerts = await (dependencies.expected_alerts or _expected_alert_map)(
        metric_repository=metric_repository,
        devices=devices,
        latest_metrics=latest_metrics,
        thresholds=thresholds,
        threshold_overrides=threshold_overrides,
        active_maintenance_windows=active_maintenance_windows,
        active_alerts=active_alerts_list,
    )
    notification_policy = dependencies.notification_policy or _telegram_notification_policy()
    queued_active_ids = (
        await pending_active_notification_ids(db, {alert.id for alert in active_alerts_list})
        if notification_writer is not None
        else set()
    )

    await _apply_created_alerts(state, expected_alerts, alert_repository, incident_repository, clock=dependencies.clock)
    await _apply_resolved_alerts(
        state,
        expected_alerts,
        alert_repository,
        incident_repository,
        device_by_id=device_by_id,
        device_type_by_id=device_type_by_id,
        notification_policy=notification_policy,
        queued_active_ids=queued_active_ids,
        clock=dependencies.clock,
    )
    await _resolve_orphans(state, incident_repository, clock=dependencies.clock)
    await _flush_alert_state_changes(db, state, commit=domain_commit)

    state.telegram_events.extend(
        _pending_active_telegram_events(
            [alert for alert in state.alerts.values() if alert.id not in queued_active_ids],
            device_by_id=device_by_id,
            device_type_by_id=device_type_by_id,
            latest_metrics=latest_metrics,
            policy=notification_policy,
            current_time=dependencies.clock(),
            recent_alert_counts=await _recent_telegram_policy_counts(
                alert_repository,
                state.alerts.values(),
                policy=notification_policy,
                current_time=dependencies.clock(),
            ),
            recent_summary_alerts=await _recent_telegram_summary_alerts(
                alert_repository,
                state.alerts.values(),
                policy=notification_policy,
                current_time=dependencies.clock(),
            ),
            recently_notified_keys=await _recent_telegram_notified_keys(
                alert_repository, state.alerts.values(), policy=notification_policy, current_time=dependencies.clock()
            ),
        )
    )
    events = _filter_recent_telegram_events(state.telegram_events)
    if notification_writer is None:
        await _send_telegram_events(
            db,
            alert_repository,
            events,
            commit=commit,
            sender=dependencies.legacy_sender or legacy_sender or send_telegram_alert,
            clock=dependencies.clock,
        )
    else:
        await notification_writer(db, _order_telegram_events(await _refresh_telegram_events(db, events)))
        if commit:
            await db.commit()
        else:
            await db.flush()
    return state.notifications
