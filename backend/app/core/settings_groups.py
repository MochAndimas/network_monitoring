"""Domain-specific settings groups built from the flat environment model."""

from dataclasses import dataclass
from typing import Literal


AppEnv = Literal["development", "production", "test"]


@dataclass(frozen=True)
class AppSettings:
    name: str
    env: AppEnv
    log_level: str

    @property
    def is_production(self) -> bool:
        return str(self.env).strip().lower() == "production"

    @property
    def is_development(self) -> bool:
        return str(self.env).strip().lower() == "development"


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: int
    pool_recycle_seconds: int
    auto_create_tables: bool


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    chat_id: str
    alert_grace_period_seconds: int
    realtime_severities: str
    summary_severities: str
    summary_interval_seconds: int
    notification_cooldown_seconds: int
    resolved_correlation_window_seconds: int


@dataclass(frozen=True)
class MikrotikSettings:
    host: str
    port: int
    username: str
    password: str
    dynamic_sections: str
    dynamic_firewall_section_allowlist: str
    dynamic_interface_allowlist: str
    dynamic_queue_allowlist: str
    dynamic_max_interfaces: int
    dynamic_max_firewall_rules: int
    dynamic_max_queues: int


@dataclass(frozen=True)
class MonitorSettings:
    ping_timeout_seconds: float
    ping_sample_count: int
    ping_concurrency_limit: int
    task_concurrency_limit: int
    lock_name: str
    lock_timeout_seconds: int
    server_resource_device_ip: str


@dataclass(frozen=True)
class SchedulerSettings:
    enabled: bool
    interval_internet_seconds: int
    interval_device_seconds: int
    interval_server_seconds: int
    interval_mikrotik_seconds: int
    interval_alert_seconds: int
    cleanup_interval_hours: int
    job_max_instances: int
    timezone: str
    job_stale_factor: int


@dataclass(frozen=True)
class InternetCheckSettings:
    dns_host: str
    http_url: str
    http_timeout_seconds: float
    http_retries: int
    public_ip_url: str


@dataclass(frozen=True)
class RetentionSettings:
    raw_metric_days: int
    rollup_batch_size: int
    archive_batch_size: int
    alert_days: int
    incident_days: int


@dataclass(frozen=True)
class DashboardSettings:
    api_url: str
    overview_cache_ttl_seconds: float


@dataclass(frozen=True)
class ObservabilitySettings:
    enable_metrics: bool
    log_as_json: bool
    request_slow_log_threshold_ms: int


@dataclass(frozen=True)
class ThresholdSettings:
    cpu_warning: float
    ram_warning: float
    disk_warning: float


@dataclass(frozen=True)
class AuthSettings:
    internal_api_key: str
    internal_api_keys: str
    password_secret: str
    token_ttl_minutes: int
    remember_ttl_minutes: int
    jwt_secret: str
    jwt_issuer: str
    jwt_algorithm: str
    cookie_name: str
    refresh_cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    login_rate_limit_max_attempts: int
    login_rate_limit_window_minutes: int
    session_touch_interval_seconds: int
    session_retention_days: int
    login_attempt_retention_days: int
    password_min_length: int
    bootstrap_admin_username: str
    bootstrap_admin_full_name: str
    bootstrap_admin_password: str
    allow_insecure_no_auth: bool


@dataclass(frozen=True)
class NetworkSecuritySettings:
    cors_origins: str
    trusted_hosts: str
    trusted_proxy_ips: str


@dataclass(frozen=True)
class SnmpSettings:
    printer_communities: str
    nas_communities: str
