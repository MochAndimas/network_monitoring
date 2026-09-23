"""Telegram selection policy; no repository writes or network delivery."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace

from ...core.config import settings
from ...core.time import utcnow
from ...models.alert import Alert
from ...models.metric import Metric
from .constants import ALERT_PRIMARY_METRIC_BY_TYPE, TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE

_DEFAULT_REALTIME_SEVERITIES = {"critical"}

_DEFAULT_REALTIME_ALERT_TYPES = {"device_down", "internet_loss", "high_packet_loss_critical"}

_DEFAULT_REALTIME_DEVICE_TYPES = {"internet_target", "voip", "switch", "server"}

_DEFAULT_SUMMARY_ALERT_TYPES = {"slow_http_response", "slow_dns_resolution"}

_SUMMARY_AGGREGATE_ALERT_TYPES = {"slow_http_response", "slow_dns_resolution"}


@dataclass(frozen=True)
class TelegramNotificationPolicy:
    """Normalized Telegram alerting policy used by notification selection."""

    realtime_severities: set[str]
    realtime_alert_types: set[str]
    realtime_device_types: set[str]
    non_realtime_device_down_summary_seconds: int
    site_outage_min_devices: int
    site_outage_window_seconds: int
    site_outage_cooldown_seconds: int
    summary_severities: set[str]
    summary_alert_types: set[str]
    alert_grace_period_seconds: int
    summary_interval_seconds: int
    summary_repeat_window_seconds: int
    summary_repeat_min_count: int
    flap_suppression_seconds: int
    flap_repeat_window_seconds: int
    flap_repeat_min_count: int
    critical_reminder_interval_seconds: int
    voip_alert_grace_period_seconds: int
    voip_critical_reminder_interval_seconds: int
    notification_cooldown_seconds: int
    resolved_correlation_window_seconds: int


def _should_send_telegram_alert(alert_type: str, device_type: str | None) -> bool:
    """Return whether an alert state change should be sent to Telegram."""
    return alert_type not in TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE.get(str(device_type or ""), set())


def _should_send_telegram_resolved_alert(alert, resolved_at, device_type: str | None) -> bool:
    """Return whether a resolved alert should be sent to Telegram."""
    if not _should_send_telegram_alert(alert.alert_type, device_type):
        return False
    return alert.telegram_notified_at is not None


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
        realtime_alert_types=_parse_alert_type_csv(
            settings.telegram.realtime_alert_types,
            fallback=_DEFAULT_REALTIME_ALERT_TYPES,
        ),
        realtime_device_types=_parse_alert_type_csv(
            settings.telegram.realtime_device_types,
            fallback=_DEFAULT_REALTIME_DEVICE_TYPES,
        ),
        non_realtime_device_down_summary_seconds=max(
            int(settings.telegram.non_realtime_device_down_summary_seconds or 0), 0
        ),
        site_outage_min_devices=max(int(settings.telegram.site_outage_min_devices or 0), 0),
        site_outage_window_seconds=max(int(settings.telegram.site_outage_window_seconds or 0), 0),
        site_outage_cooldown_seconds=max(int(settings.telegram.site_outage_cooldown_seconds or 0), 0),
        summary_severities=_parse_severity_csv(settings.telegram.summary_severities),
        summary_alert_types=_parse_alert_type_csv(
            settings.telegram.summary_alert_types,
            fallback=_DEFAULT_SUMMARY_ALERT_TYPES,
        ),
        alert_grace_period_seconds=max(int(settings.telegram.alert_grace_period_seconds or 0), 0),
        summary_interval_seconds=max(int(settings.telegram.summary_interval_seconds or 0), 0),
        summary_repeat_window_seconds=max(int(settings.telegram.summary_repeat_window_seconds or 0), 0),
        summary_repeat_min_count=max(int(settings.telegram.summary_repeat_min_count or 0), 0),
        flap_suppression_seconds=max(int(settings.telegram.flap_suppression_seconds or 0), 0),
        flap_repeat_window_seconds=max(int(settings.telegram.flap_repeat_window_seconds or 0), 0),
        flap_repeat_min_count=max(int(settings.telegram.flap_repeat_min_count or 0), 0),
        critical_reminder_interval_seconds=max(int(settings.telegram.critical_reminder_interval_seconds or 0), 0),
        voip_alert_grace_period_seconds=max(int(settings.telegram.voip_alert_grace_period_seconds or 0), 0),
        voip_critical_reminder_interval_seconds=max(
            int(settings.telegram.voip_critical_reminder_interval_seconds or 0), 0
        ),
        notification_cooldown_seconds=max(int(settings.telegram.notification_cooldown_seconds or 0), 0),
        resolved_correlation_window_seconds=max(int(settings.telegram.resolved_correlation_window_seconds or 0), 0),
    )


def _parse_alert_type_csv(raw_value: str, *, fallback: set[str] | None = None) -> set[str]:
    """Parse comma-separated alert types into normalized identifiers."""
    values = {item.strip().lower() for item in str(raw_value or "").split(",") if item.strip()}
    return values or set(fallback or set())


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
    recent_alert_counts: dict[tuple[int | None, str], int] | None = None,
    recent_summary_alerts: dict[int | None, list[Alert]] | None = None,
    recently_notified_keys: set[tuple[int | None, str]] | None = None,
    current_time: datetime | None = None,
) -> list[dict]:
    """Return active alerts ready for Telegram based on realtime and summary rules."""
    alerts = list(alerts)
    policy = policy or _telegram_notification_policy()
    recent_alert_counts = recent_alert_counts or {}
    recent_summary_alerts = recent_summary_alerts or {}
    recently_notified_keys = recently_notified_keys or set()
    current_time = current_time if current_time is not None else utcnow()
    events: list[dict] = []
    unreachable_device_ids = {
        alert.device_id for alert in alerts if str(alert.alert_type or "").lower() in {"device_down", "internet_loss"}
    }
    for alert in alerts:
        device_type = device_type_by_id.get(alert.device_id) if alert.device_id is not None else None
        if not _should_send_telegram_alert(alert.alert_type, device_type):
            continue
        if _active_alert_metric_is_stale(alert, latest_metrics, current_time=current_time):
            continue
        alert_severity = str(alert.severity or "unknown").lower()
        alert_type = str(alert.alert_type or "").lower()
        if alert.telegram_notified_at is None and (alert.device_id, alert_type) in recently_notified_keys:
            continue
        # Packet loss is not actionable once the same device is unreachable.
        if alert_type == "high_packet_loss_critical" and alert.device_id in unreachable_device_ids:
            continue
        realtime_device_allowed = _telegram_realtime_device_allowed(
            alert_type,
            device_by_id.get(alert.device_id),
            policy=policy,
        )
        should_send_realtime = (
            alert_severity in policy.realtime_severities
            and alert_type in policy.realtime_alert_types
            and realtime_device_allowed
            and _alert_passes_flap_suppression(
                alert,
                current_time,
                policy=policy,
                recent_alert_count=recent_alert_counts.get((alert.device_id, alert_type), 0),
            )
            and _alert_reached_telegram_grace_period(
                alert.created_at,
                current_time,
                grace_period_seconds=_telegram_alert_grace_period_seconds(device_type, policy=policy),
            )
            and _alert_reached_telegram_cooldown(
                alert.telegram_notified_at,
                current_time,
                cooldown_seconds=_active_telegram_cooldown_seconds(alert, device_type=device_type, policy=policy),
            )
        )
        should_send_summary = (
            _telegram_summary_allowed(
                alert_type,
                alert_severity,
                realtime_device_allowed=realtime_device_allowed,
                policy=policy,
            )
            and _alert_reached_summary_delivery_threshold(
                alert,
                current_time,
                alert_type=alert_type,
                realtime_device_allowed=realtime_device_allowed,
                policy=policy,
                recent_alert_count=recent_alert_counts.get((alert.device_id, alert_type), 0),
            )
            and _alert_reached_telegram_grace_period(
                alert.created_at,
                current_time,
                grace_period_seconds=_telegram_alert_grace_period_seconds(device_type, policy=policy),
            )
            and _alert_reached_telegram_cooldown(
                alert.telegram_notified_at,
                current_time,
                cooldown_seconds=policy.notification_cooldown_seconds,
            )
            and alert.telegram_notified_at is None
        )
        if not should_send_realtime and not should_send_summary:
            continue
        action = _telegram_active_event_action(
            alert, should_send_summary=should_send_summary, should_send_realtime=should_send_realtime
        )
        events.append(
            {
                "action": action,
                "alert": alert,
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "device": device_by_id.get(alert.device_id),
                "summary_alerts": recent_summary_alerts.get(alert.device_id, []),
            }
        )
    return _collapse_site_outage_events(
        events, alerts, device_by_id=device_by_id, policy=policy, current_time=current_time
    )


def _collapse_site_outage_events(
    events: list[dict],
    alerts: list[Alert],
    *,
    device_by_id: dict,
    policy: TelegramNotificationPolicy,
    current_time: datetime,
) -> list[dict]:
    """Replace a burst of same-site device-down messages with one outage message."""
    if policy.site_outage_min_devices <= 1 or policy.site_outage_window_seconds <= 0:
        return events
    by_site: dict[str, list[Alert]] = {}
    for alert in alerts:
        if str(alert.alert_type or "").lower() != "device_down" or alert.device_id is None:
            continue
        device = device_by_id.get(alert.device_id)
        site = str(getattr(device, "site", "") or "").strip()
        if not site or alert.created_at > current_time - timedelta(seconds=policy.site_outage_window_seconds):
            continue
        by_site.setdefault(site, []).append(alert)
    collapsed_ids: set[int] = set()
    outage_events: list[dict] = []
    for site, site_alerts in by_site.items():
        if len(site_alerts) < policy.site_outage_min_devices:
            continue
        collapsed_ids.update(alert.id for alert in site_alerts if alert.id is not None)
        names = [str(getattr(device_by_id.get(alert.device_id), "name", alert.device_id)) for alert in site_alerts]
        representative = site_alerts[0]
        outage_events.append(
            {
                "action": "active",
                "alert": representative,
                "alerts": site_alerts,
                "alert_id": representative.id,
                "alert_type": "site_outage",
                "severity": "critical",
                "message": f"{len(site_alerts)} devices unreachable: {', '.join(sorted(names))}",
                "device": SimpleNamespace(
                    id=f"site:{site}", name=f"Site outage: {site}", ip_address="-", site=site, device_type="site"
                ),
            }
        )
    if not collapsed_ids:
        return events
    return [event for event in events if event.get("alert_id") not in collapsed_ids] + outage_events


def _telegram_realtime_device_allowed(alert_type: str, device, *, policy: TelegramNotificationPolicy) -> bool:
    """Return whether a device is important enough for realtime Telegram."""
    if not policy.realtime_device_types:
        return True
    return str(getattr(device, "device_type", "") or "").strip().lower() in policy.realtime_device_types


def _telegram_summary_allowed(
    alert_type: str,
    alert_severity: str,
    *,
    realtime_device_allowed: bool,
    policy: TelegramNotificationPolicy,
) -> bool:
    """Return whether an active alert can be sent through Telegram digest."""
    if alert_type == "device_down" and not realtime_device_allowed:
        return True
    if alert_severity in policy.summary_severities and alert_type in policy.summary_alert_types:
        return True
    return alert_type == "high_packet_loss_critical" and alert_severity == "critical" and not realtime_device_allowed


def _alert_reached_summary_delivery_threshold(
    alert,
    current_time: datetime,
    *,
    alert_type: str,
    realtime_device_allowed: bool,
    policy: TelegramNotificationPolicy,
    recent_alert_count: int,
) -> bool:
    """Use the shorter non-critical-device window before delivering a down digest."""
    if alert_type == "device_down" and not realtime_device_allowed:
        return _alert_reached_summary_interval(
            alert.created_at,
            current_time,
            summary_interval_seconds=policy.non_realtime_device_down_summary_seconds,
        )
    return _alert_reached_telegram_summary_threshold(
        alert, current_time, policy=policy, recent_alert_count=recent_alert_count
    )


def _alert_passes_flap_suppression(
    alert,
    current_time: datetime,
    *,
    policy: TelegramNotificationPolicy,
    recent_alert_count: int,
) -> bool:
    """Suppress one-off fast device-down flaps unless they repeat."""
    if str(alert.alert_type or "").lower() != "device_down":
        return True
    if policy.flap_suppression_seconds <= 0:
        return True
    if alert.created_at <= current_time - timedelta(seconds=policy.flap_suppression_seconds):
        return True
    if policy.flap_repeat_window_seconds <= 0 or policy.flap_repeat_min_count <= 1:
        return False
    return int(recent_alert_count or 0) >= policy.flap_repeat_min_count


def _telegram_alert_grace_period_seconds(device_type: str | None, *, policy: TelegramNotificationPolicy) -> int:
    """Return the Telegram grace period for a device type."""
    if str(device_type or "").strip().lower() == "voip":
        return policy.voip_alert_grace_period_seconds
    return policy.alert_grace_period_seconds


def _active_telegram_cooldown_seconds(
    alert,
    *,
    device_type: str | None,
    policy: TelegramNotificationPolicy,
) -> int:
    """Return cooldown seconds for first sends and active critical reminders."""
    if alert.telegram_notified_at is not None and str(alert.severity or "").lower() == "critical":
        if str(device_type or "").strip().lower() == "voip":
            return policy.voip_critical_reminder_interval_seconds
        return policy.critical_reminder_interval_seconds
    return policy.notification_cooldown_seconds


def _telegram_active_event_action(alert, *, should_send_summary: bool, should_send_realtime: bool) -> str:
    """Return the active Telegram action name for a selected alert."""
    if should_send_summary and not should_send_realtime:
        return "summary_active"
    if alert.telegram_notified_at is not None:
        return "active_reminder"
    return "active"


def _alert_reached_telegram_summary_threshold(
    alert,
    current_time: datetime,
    *,
    policy: TelegramNotificationPolicy,
    recent_alert_count: int,
) -> bool:
    """Return whether an alert is old or repetitive enough for summary delivery."""
    if _alert_reached_summary_interval(
        alert.created_at,
        current_time,
        summary_interval_seconds=policy.summary_interval_seconds,
    ):
        return True
    if policy.summary_repeat_window_seconds <= 0 or policy.summary_repeat_min_count <= 1:
        return False
    return int(recent_alert_count or 0) >= policy.summary_repeat_min_count


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
    if not isinstance(checked_at, datetime):
        return True
    return checked_at <= current_time - timedelta(seconds=stale_after_seconds)


def _alert_metric_stale_after_seconds() -> int:
    """Return alert freshness window based on scheduler cadence."""
    return max(
        int(settings.scheduler.interval_device_seconds) * max(int(settings.scheduler.job_stale_factor), 1),
        60,
    )
