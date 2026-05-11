"""Telegram notification helpers for alert state changes."""

from .impl import (
    TELEGRAM_NOTIFICATION_DEDUPE_TTL,
    TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE,
    _build_telegram_message,
    _build_telegram_messages,
    _filter_recent_telegram_events,
    _format_alert_duration,
    _format_telegram_alert_line,
    _group_telegram_events,
    _order_telegram_events,
    _pending_active_telegram_events,
    _refresh_telegram_events,
    _send_telegram_events,
    _should_send_telegram_alert,
    _should_send_telegram_resolved_alert,
    _telegram_notification_key,
)

__all__ = [
    "TELEGRAM_NOTIFICATION_DEDUPE_TTL",
    "TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE",
    "_build_telegram_message",
    "_build_telegram_messages",
    "_filter_recent_telegram_events",
    "_format_alert_duration",
    "_format_telegram_alert_line",
    "_group_telegram_events",
    "_order_telegram_events",
    "_pending_active_telegram_events",
    "_refresh_telegram_events",
    "_send_telegram_events",
    "_should_send_telegram_alert",
    "_should_send_telegram_resolved_alert",
    "_telegram_notification_key",
]
