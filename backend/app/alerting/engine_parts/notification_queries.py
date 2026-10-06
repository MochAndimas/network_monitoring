"""Notification queries: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import datetime, timedelta

from ...core.time import utcnow
from ...models.alert import Alert
from ...repositories.alert_repository import AlertRepository
from .notification_policy import _SUMMARY_AGGREGATE_ALERT_TYPES
from .notification_policy import TelegramNotificationPolicy as TelegramNotificationPolicy


async def _resolved_alert_recently_notified(
    alert_repository: AlertRepository,
    *,
    alert,
    resolved_at: datetime,
    policy: TelegramNotificationPolicy,
    current_time: datetime | None = None,
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
    current_time: datetime | None = None,
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
        since=(current_time if current_time is not None else utcnow()) - timedelta(seconds=lookback_seconds),
    )


async def _recent_telegram_summary_alerts(
    alert_repository: AlertRepository,
    alerts,
    *,
    policy: TelegramNotificationPolicy,
    current_time: datetime | None = None,
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
        since=(current_time if current_time is not None else utcnow())
        - timedelta(seconds=policy.summary_repeat_window_seconds),
    )


async def _recent_telegram_notified_keys(
    alert_repository: AlertRepository,
    alerts,
    *,
    policy: TelegramNotificationPolicy,
    current_time: datetime | None = None,
) -> set[tuple[int | None, str]]:
    """Keep cooldown after a flap creates a replacement alert row."""
    if policy.notification_cooldown_seconds <= 0:
        return set()
    keys = {(alert.device_id, str(alert.alert_type or "").lower()) for alert in alerts}
    return await alert_repository.recent_telegram_notified_keys(
        keys,
        since=(current_time if current_time is not None else utcnow())
        - timedelta(seconds=policy.notification_cooldown_seconds),
    )
