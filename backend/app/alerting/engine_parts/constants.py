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
ALERT_PRIMARY_METRIC_BY_TYPE = {
    "device_down": "ping",
    "internet_loss": "ping",
    "high_ping_latency_warning": "ping",
    "high_ping_latency_critical": "ping",
    "high_packet_loss_warning": "packet_loss",
    "high_packet_loss_critical": "packet_loss",
    "high_jitter_warning": "jitter",
    "high_jitter_critical": "jitter",
    "dns_resolution_failed": "dns_resolution_time",
    "slow_dns_resolution": "dns_resolution_time",
    "http_check_failed": "http_response_time",
    "slow_http_response": "http_response_time",
    "public_ip_changed": "public_ip",
    "cpu_usage_high": "cpu_percent",
    "memory_usage_high": "memory_percent",
    "disk_usage_high": "disk_percent",
    "mikrotik_api_failed": "mikrotik_api",
    "mikrotik_connected_clients_high": "connected_clients",
}

__all__ = [
    "ALERT_DYNAMIC_METRIC_NAME_PATTERNS",
    "ALERT_EXACT_METRIC_NAMES",
    "ALERT_PRIMARY_METRIC_BY_TYPE",
    "TELEGRAM_NOTIFICATION_DEDUPE_TTL",
    "TELEGRAM_SUPPRESSED_ALERT_TYPES_BY_DEVICE_TYPE",
]
