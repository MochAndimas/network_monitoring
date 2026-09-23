"""Telegram event grouping and message rendering, independent of delivery."""

from datetime import datetime
import re

from ...core.config import settings
from ...models.alert import Alert
from .notification_policy import _SUMMARY_AGGREGATE_ALERT_TYPES


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


def _group_telegram_events(events: list[dict]) -> dict[tuple[str, str, str], list[dict]]:
    """Group simultaneous Telegram events by site, state, and severity."""
    grouped_events: dict[tuple[str, str, str], list[dict]] = {}
    for event in events:
        device = event.get("device")
        site = str(getattr(device, "site", None) or "Unassigned").strip() or "Unassigned"
        group_key = (
            site.casefold(),
            str(event.get("action") or "active").lower(),
            str(event.get("severity") or "unknown").lower(),
        )
        grouped_events.setdefault(group_key, []).append(event)
    return grouped_events


def _order_telegram_events(events: list[dict]) -> list[dict]:
    """Keep active notifications ahead of resolved notifications in the same send batch."""
    action_rank = {"active": 0, "active_reminder": 1, "summary_active": 2, "created": 2, "resolved": 3}
    return sorted(events, key=lambda event: action_rank.get(str(event.get("action") or "active").lower(), 0))


def _build_telegram_message(events: list[dict]) -> str:
    """Build a Telegram message for one device or a same-site alert batch."""
    first_event = events[0]
    action = str(first_event.get("action") or "").lower()
    is_resolved = str(action or "").lower() == "resolved"
    is_summary = str(action or "").lower() == "summary_active"
    is_reminder = str(action or "").lower() == "active_reminder"
    title = (
        "ALERT RESOLVED"
        if is_resolved
        else ("ALERT SUMMARY" if is_summary else "ALERT REMINDER" if is_reminder else "ALERT ACTIVE")
    )
    status = "RESOLVED" if is_resolved else ("SUMMARY" if is_summary else "ACTIVE")
    severity = _highest_severity(str(event.get("severity") or "unknown") for event in events)
    device = first_event.get("device")
    device_name = getattr(device, "name", None) or "-"
    ip_address = getattr(device, "ip_address", None) or "-"
    site = getattr(device, "site", None) or "-"
    location = str(getattr(device, "location", None) or "").strip()
    device_type = getattr(device, "device_type", None) or "-"
    alert_lines = [
        _format_telegram_alert_line(event, include_duration=is_resolved)
        for event in sorted(events, key=lambda item: str(item.get("alert_type") or ""))
    ]
    if is_summary:
        alert_lines = _format_telegram_summary_alert_lines(events, device_name=device_name)
    unique_device_ids = {getattr(item.get("device"), "id", None) for item in events}
    if len(unique_device_ids) > 1:
        return _build_batched_telegram_message(
            events,
            title=title,
            status=status,
            severity=severity,
            include_duration=is_resolved,
        )
    details = [
        settings.app.name or "Network Monitoring",
        f"[{str(severity or 'unknown').upper()}] {title}",
        f"Device: {device_name}",
        f"IP: {ip_address}",
        f"Site: {site}",
    ]
    if location:
        details.append(f"Location: {location}")
    return "\n".join([*details, f"Type: {device_type}", f"Status: {status}", "Alerts:", *alert_lines])


def _build_batched_telegram_message(
    events: list[dict],
    *,
    title: str,
    status: str,
    severity: str,
    include_duration: bool,
) -> str:
    """Build one concise Telegram message for simultaneous same-site device alerts."""
    first_device = events[0].get("device")
    site = getattr(first_device, "site", None) or "Unassigned"
    device_ids = {getattr(event.get("device"), "id", None) for event in events}
    alert_lines = [
        _format_batched_telegram_alert_line(event, include_duration=include_duration)
        for event in sorted(
            events, key=lambda item: (str(getattr(item.get("device"), "name", "")), str(item.get("alert_type") or ""))
        )
    ]
    return "\n".join(
        [
            settings.app.name or "Network Monitoring",
            f"[{str(severity or 'unknown').upper()}] {title}",
            f"Site: {site}",
            f"Devices affected: {len(device_ids)}",
            f"Status: {status}",
            "Alerts:",
            *alert_lines,
        ]
    )


def _format_batched_telegram_alert_line(event: dict, *, include_duration: bool) -> str:
    """Format one device alert line inside a same-site Telegram batch."""
    device = event.get("device")
    device_name = getattr(device, "name", None) or "-"
    ip_address = getattr(device, "ip_address", None) or "-"
    location = str(getattr(device, "location", None) or "").strip()
    location_suffix = f" | {location}" if location else ""
    line = f"- {device_name} ({ip_address}{location_suffix}): {event['alert_type']}: {event['message']}"
    if not include_duration:
        return line
    duration = _format_alert_duration(event.get("created_at"), event.get("resolved_at"))
    return f"{line} (duration: {duration})" if duration is not None else line


def _format_telegram_alert_line(event: dict, *, include_duration: bool) -> str:
    """Format one Telegram alert line, optionally including resolved duration."""
    line = f"- {event['alert_type']}: {event['message']}"
    if not include_duration:
        return line

    duration = _format_alert_duration(event.get("created_at"), event.get("resolved_at"))
    if duration is None:
        return line
    return f"{line} (duration: {duration})"


def _format_telegram_summary_alert_lines(events: list[dict], *, device_name: str) -> list[str]:
    """Format summary events as one aggregate incident/device digest when possible."""
    summary_alerts = _summary_alerts_for_events(events)
    aggregate_alerts = [
        alert
        for alert in summary_alerts
        if str(getattr(alert, "alert_type", "") or "").lower() in _SUMMARY_AGGREGATE_ALERT_TYPES
    ]
    if not aggregate_alerts:
        return [
            _format_telegram_alert_line(event, include_duration=False)
            for event in sorted(events, key=lambda item: str(item.get("alert_type") or ""))
        ]

    return [_format_degraded_summary_line(device_name=device_name, alerts=aggregate_alerts)]


def _summary_alerts_for_events(events: list[dict]) -> list[Alert]:
    """Return unique recent alerts carried by summary events."""
    alerts_by_id = {}
    for event in events:
        for alert in event.get("summary_alerts") or []:
            alerts_by_id[getattr(alert, "id", id(alert))] = alert
    return list(alerts_by_id.values())


def _format_degraded_summary_line(*, device_name: str, alerts: list[Alert]) -> str:
    """Return one concise degraded-service summary line for HTTP/DNS alerts."""
    ordered_alerts = sorted(alerts, key=lambda alert: (alert.created_at, alert.id or 0))
    started_at = ordered_alerts[0].created_at
    ended_at = max((alert.resolved_at or alert.created_at) for alert in ordered_alerts)
    counts = {
        "slow_http_response": sum(1 for alert in ordered_alerts if alert.alert_type == "slow_http_response"),
        "slow_dns_resolution": sum(1 for alert in ordered_alerts if alert.alert_type == "slow_dns_resolution"),
    }
    parts = [
        f"{counts['slow_http_response']} slow HTTP" if counts["slow_http_response"] else "",
        f"{counts['slow_dns_resolution']} slow DNS" if counts["slow_dns_resolution"] else "",
    ]
    max_http_ms = _max_metric_ms(ordered_alerts, "slow_http_response")
    max_dns_ms = _max_metric_ms(ordered_alerts, "slow_dns_resolution")
    if max_http_ms is not None:
        parts.append(f"max HTTP {_format_metric_latency(max_http_ms)}")
    if max_dns_ms is not None:
        parts.append(f"max DNS {_format_metric_latency(max_dns_ms)}")
    summary = ", ".join(part for part in parts if part)
    return f"- {device_name} degraded {_format_summary_window(started_at, ended_at)}: {summary}"


def _max_metric_ms(alerts: list[Alert], alert_type: str) -> float | None:
    """Extract the maximum millisecond value from alert messages for one alert type."""
    values = [
        float(match.group(1))
        for alert in alerts
        if alert.alert_type == alert_type
        for match in [re.search(r"reached\s+([0-9]+(?:\.[0-9]+)?)ms", str(alert.message or ""))]
        if match
    ]
    return max(values) if values else None


def _format_metric_latency(value_ms: float) -> str:
    """Format latency in ms or seconds for compact Telegram summaries."""
    if value_ms >= 1000:
        return f"{value_ms / 1000:.1f}s"
    return f"{value_ms:.0f}ms"


def _format_summary_window(started_at: datetime, ended_at: datetime) -> str:
    """Format the time window for a summary Telegram line."""
    return f"{started_at:%H:%M}-{ended_at:%H:%M}"


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
