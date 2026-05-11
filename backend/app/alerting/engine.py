"""Compatibility facade for alert evaluation.

The implementation is split under ``backend.app.alerting.engine_parts``.
This module keeps the historical import path stable for scheduler jobs and tests,
including module-level monkeypatch points such as ``send_telegram_alert``.
"""

from .engine_parts import impl as _impl

TELEGRAM_NOTIFICATION_DEDUPE_TTL = _impl.TELEGRAM_NOTIFICATION_DEDUPE_TTL
TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE = _impl.TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE
_recent_telegram_notification_keys = _impl._recent_telegram_notification_keys
settings = _impl.settings
send_telegram_alert = _impl.send_telegram_alert


def _sync_patchable_globals() -> None:
    """Forward facade-level monkeypatches into the implementation module."""
    _impl.send_telegram_alert = send_telegram_alert


async def evaluate_alerts(db, *, commit: bool = True) -> list[dict]:
    """Evaluate alert state while preserving historical monkeypatch behavior."""
    _sync_patchable_globals()
    return await _impl.evaluate_alerts(db, commit=commit)


async def _send_telegram_events(db, alert_repository, events: list[dict], *, commit: bool) -> None:
    """Send Telegram events while preserving historical monkeypatch behavior."""
    _sync_patchable_globals()
    await _impl._send_telegram_events(db, alert_repository, events, commit=commit)


_alert_reached_telegram_grace_period = _impl._alert_reached_telegram_grace_period
_build_alert_payload = _impl._build_alert_payload
_build_telegram_message = _impl._build_telegram_message
_build_telegram_messages = _impl._build_telegram_messages
_evaluate_mikrotik_alerts = _impl._evaluate_mikrotik_alerts
_filter_recent_telegram_events = _impl._filter_recent_telegram_events
_format_alert_duration = _impl._format_alert_duration
_format_telegram_alert_line = _impl._format_telegram_alert_line
_group_telegram_events = _impl._group_telegram_events
_highest_dynamic_metric = _impl._highest_dynamic_metric
_highest_severity = _impl._highest_severity
_metric_numeric_value = _impl._metric_numeric_value
_order_telegram_events = _impl._order_telegram_events
_pending_active_telegram_events = _impl._pending_active_telegram_events
_refresh_telegram_events = _impl._refresh_telegram_events
_resolve_incident_if_cleared = _impl._resolve_incident_if_cleared
_should_send_telegram_alert = _impl._should_send_telegram_alert
_should_send_telegram_resolved_alert = _impl._should_send_telegram_resolved_alert
_telegram_notification_key = _impl._telegram_notification_key
_threshold_for_device = _impl._threshold_for_device

__all__ = [
    "TELEGRAM_NOTIFICATION_DEDUPE_TTL",
    "TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE",
    "_recent_telegram_notification_keys",
    "evaluate_alerts",
    "send_telegram_alert",
    "settings",
    "_alert_reached_telegram_grace_period",
    "_build_alert_payload",
    "_build_telegram_message",
    "_build_telegram_messages",
    "_evaluate_mikrotik_alerts",
    "_filter_recent_telegram_events",
    "_format_alert_duration",
    "_format_telegram_alert_line",
    "_group_telegram_events",
    "_highest_dynamic_metric",
    "_highest_severity",
    "_metric_numeric_value",
    "_order_telegram_events",
    "_pending_active_telegram_events",
    "_refresh_telegram_events",
    "_resolve_incident_if_cleared",
    "_send_telegram_events",
    "_should_send_telegram_alert",
    "_should_send_telegram_resolved_alert",
    "_telegram_notification_key",
    "_threshold_for_device",
]
