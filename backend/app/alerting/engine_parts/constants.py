"""Constants used by alert evaluation and notification orchestration."""

from datetime import timedelta

TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE = {
    "voip": {
        "high_ping_latency_warning",
        "high_ping_latency_critical",
        "high_jitter_warning",
        "high_jitter_critical",
    },
    "printer": {
        "high_ping_latency_warning",
        "high_ping_latency_critical",
        "high_jitter_warning",
        "high_jitter_critical",
    },
}
TELEGRAM_NOTIFICATION_DEDUPE_TTL = timedelta(minutes=5)
ALERT_EXACT_METRIC_NAMES = {
    "ping",
    "packet_loss",
    "jitter",
    "dns_resolution_time",
    "http_response_time",
    "public_ip",
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "mikrotik_api",
    "connected_clients",
    "printer_uptime_seconds",
    "printer_status",
    "printer_error_state",
    "printer_paper_status",
    "printer_ink_status",
    "nas_system_status",
    "nas_power_status",
    "nas_system_temperature_c",
}
ALERT_DYNAMIC_METRIC_NAME_PATTERNS = (
    "interface:%:rx_mbps",
    "interface:%:tx_mbps",
    "firewall:%:pps",
    "firewall:%:mbps",
    "nas_fan:%:status",
    "nas_volume:%:status",
    "nas_raid:%:status",
    "nas_disk:%:status",
    "nas_disk:%:temperature_c",
)

__all__ = [
    "ALERT_DYNAMIC_METRIC_NAME_PATTERNS",
    "ALERT_EXACT_METRIC_NAMES",
    "TELEGRAM_NOTIFICATION_DEDUPE_TTL",
    "TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE",
]
