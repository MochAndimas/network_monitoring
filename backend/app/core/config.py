"""Application settings, environment validation, and logging setup."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .settings_groups import (
    AppEnv,
    AppSettings,
    AuthSettings,
    DashboardSettings,
    DatabaseSettings,
    InternetCheckSettings,
    MikrotikSettings,
    MonitorSettings,
    NetworkSecuritySettings,
    ObservabilitySettings,
    RetentionSettings,
    SchedulerSettings,
    SnmpSettings,
    TelegramSettings,
    ThresholdSettings,
)

PRODUCTION_REQUIRED_FIELDS = (
    "auth_password_secret",
    "auth_jwt_secret",
    "cors_origins",
    "trusted_hosts",
)


def _split_csv(raw_value: str) -> list[str]:
    """Split a comma-separated setting into trimmed non-empty values."""
    return [item.strip() for item in str(raw_value or "").split(",") if item.strip()]


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables and optional secret files."""
    app_name: str = "Network Monitoring"
    app_env: AppEnv = "development"
    database_url: str = "mysql+pymysql://network_monitoring:change-me@localhost:3306/network_monitoring"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    database_auto_create_tables: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alert_grace_period_seconds: int = 60
    mikrotik_host: str = ""
    mikrotik_port: int = 8728
    mikrotik_username: str = ""
    mikrotik_password: str = ""
    mikrotik_dynamic_sections: str = "interface,firewall,queue"
    mikrotik_dynamic_firewall_section_allowlist: str = "filter,nat"
    mikrotik_dynamic_interface_allowlist: str = ""
    mikrotik_dynamic_queue_allowlist: str = ""
    mikrotik_dynamic_max_interfaces: int = 64
    mikrotik_dynamic_max_firewall_rules: int = 128
    mikrotik_dynamic_max_queues: int = 64
    dashboard_api_url: str = "http://localhost:8000"
    ping_timeout_seconds: float = 2.0
    ping_sample_count: int = 3
    ping_concurrency_limit: int = 32
    monitor_task_concurrency_limit: int = 16
    scheduler_enabled: bool = True
    scheduler_interval_internet_seconds: int = 30
    scheduler_interval_device_seconds: int = 60
    scheduler_interval_server_seconds: int = 60
    scheduler_interval_mikrotik_seconds: int = 60
    scheduler_interval_alert_seconds: int = 30
    scheduler_job_max_instances: int = 1
    scheduler_timezone: str = "Asia/Jakarta"
    monitoring_lock_name: str = "network_monitoring.pipeline"
    monitoring_lock_timeout_seconds: int = 900
    dns_check_host: str = "google.com"
    http_check_url: str = "https://www.google.com/generate_204"
    http_check_timeout_seconds: float = 5.0
    http_check_retries: int = 2
    public_ip_check_url: str = "https://api.ipify.org"
    raw_metric_retention_days: int = 7
    retention_rollup_batch_size: int = 500
    retention_archive_batch_size: int = 500
    alert_retention_days: int = 180
    incident_retention_days: int = 180
    scheduler_cleanup_interval_hours: int = 24
    scheduler_job_stale_factor: int = 3
    dashboard_overview_cache_ttl_seconds: float = 5.0
    observability_enable_metrics: bool = True
    log_as_json: bool = True
    request_slow_log_threshold_ms: int = 1000
    cpu_warning_threshold: float = 90.0
    ram_warning_threshold: float = 90.0
    disk_warning_threshold: float = 85.0
    server_resource_device_ip: str = ""
    internal_api_key: str = ""
    internal_api_keys: str = ""
    auth_password_secret: str = ""
    printer_snmp_communities: str = ""
    nas_snmp_communities: str = ""
    auth_token_ttl_minutes: int = 720
    auth_remember_ttl_minutes: int = 10080
    auth_jwt_secret: str = ""
    auth_jwt_issuer: str = "network-monitoring"
    auth_jwt_algorithm: str = "HS256"
    auth_cookie_name: str = "network_monitoring_session"
    auth_refresh_cookie_name: str = "network_monitoring_refresh"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_login_rate_limit_max_attempts: int = 5
    auth_login_rate_limit_window_minutes: int = 15
    auth_session_touch_interval_seconds: int = 300
    auth_session_retention_days: int = 30
    auth_login_attempt_retention_days: int = 7
    auth_password_min_length: int = 12
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_full_name: str = "Monitoring Admin"
    bootstrap_admin_password: str = ""
    allow_insecure_no_auth: bool = False
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    trusted_hosts: str = "localhost,127.0.0.1"
    trusted_proxy_ips: str = ""
    log_level: str = "INFO"
    telegram_bot_token_file: str | None = None
    telegram_chat_id_file: str | None = None
    mikrotik_password_file: str | None = None
    internal_api_key_file: str | None = None
    auth_password_secret_file: str | None = None
    printer_snmp_communities_file: str | None = None
    nas_snmp_communities_file: str | None = None
    bootstrap_admin_password_file: str | None = None
    auth_jwt_secret_file: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def load_file_backed_secrets(self) -> "Settings":
        """Load production secrets from configured files and copy them onto the settings model."""
        secret_fields = {
            "telegram_bot_token": self.telegram_bot_token_file,
            "telegram_chat_id": self.telegram_chat_id_file,
            "mikrotik_password": self.mikrotik_password_file,
            "internal_api_key": self.internal_api_key_file,
            "auth_password_secret": self.auth_password_secret_file,
            "printer_snmp_communities": self.printer_snmp_communities_file,
            "nas_snmp_communities": self.nas_snmp_communities_file,
            "bootstrap_admin_password": self.bootstrap_admin_password_file,
            "auth_jwt_secret": self.auth_jwt_secret_file,
        }
        configured_file_backed_fields = {
            field_name: str(raw_file_path).strip()
            for field_name, raw_file_path in secret_fields.items()
            if str(raw_file_path or "").strip()
        }
        if configured_file_backed_fields and not self.is_production:
            configured_names = ", ".join(sorted(configured_file_backed_fields))
            raise ValueError(
                f"File-backed secret fields ({configured_names}) are only allowed when APP_ENV=production."
            )
        for field_name, raw_file_path in secret_fields.items():
            if not raw_file_path:
                continue
            file_path = Path(raw_file_path)
            try:
                file_value = file_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ValueError(
                    f"Unable to read file-backed secret for `{field_name}` from `{file_path}`."
                ) from exc
            object.__setattr__(self, field_name, file_value)
        return self

    @model_validator(mode="after")
    def validate_environment_config(self) -> "Settings":
        """Validate environment-specific configuration."""
        if not self.is_production:
            return self

        missing_fields = [
            field_name
            for field_name in PRODUCTION_REQUIRED_FIELDS
            if not str(getattr(self, field_name, "") or "").strip()
        ]
        if missing_fields:
            formatted_fields = ", ".join(sorted(missing_fields))
            raise ValueError(f"Production configuration is missing required fields: {formatted_fields}.")
        return self

    @property
    def app(self) -> AppSettings:
        """Return app/runtime settings grouped by domain."""
        return AppSettings(name=self.app_name, env=self.app_env, log_level=self.log_level)

    @property
    def database(self) -> DatabaseSettings:
        """Return database settings grouped by domain."""
        return DatabaseSettings(
            url=self.database_url,
            pool_size=self.db_pool_size,
            max_overflow=self.db_max_overflow,
            pool_timeout_seconds=self.db_pool_timeout_seconds,
            pool_recycle_seconds=self.db_pool_recycle_seconds,
            auto_create_tables=self.database_auto_create_tables,
        )

    @property
    def telegram(self) -> TelegramSettings:
        """Return Telegram notification settings grouped by domain."""
        return TelegramSettings(
            bot_token=self.telegram_bot_token,
            chat_id=self.telegram_chat_id,
            alert_grace_period_seconds=self.telegram_alert_grace_period_seconds,
        )

    @property
    def mikrotik(self) -> MikrotikSettings:
        """Return Mikrotik monitor settings grouped by domain."""
        return MikrotikSettings(
            host=self.mikrotik_host,
            port=self.mikrotik_port,
            username=self.mikrotik_username,
            password=self.mikrotik_password,
            dynamic_sections=self.mikrotik_dynamic_sections,
            dynamic_firewall_section_allowlist=self.mikrotik_dynamic_firewall_section_allowlist,
            dynamic_interface_allowlist=self.mikrotik_dynamic_interface_allowlist,
            dynamic_queue_allowlist=self.mikrotik_dynamic_queue_allowlist,
            dynamic_max_interfaces=self.mikrotik_dynamic_max_interfaces,
            dynamic_max_firewall_rules=self.mikrotik_dynamic_max_firewall_rules,
            dynamic_max_queues=self.mikrotik_dynamic_max_queues,
        )

    @property
    def monitor(self) -> MonitorSettings:
        """Return monitor runtime settings grouped by domain."""
        return MonitorSettings(
            ping_timeout_seconds=self.ping_timeout_seconds,
            ping_sample_count=self.ping_sample_count,
            ping_concurrency_limit=self.ping_concurrency_limit,
            task_concurrency_limit=self.monitor_task_concurrency_limit,
            lock_name=self.monitoring_lock_name,
            lock_timeout_seconds=self.monitoring_lock_timeout_seconds,
            server_resource_device_ip=self.server_resource_device_ip,
        )

    @property
    def scheduler(self) -> SchedulerSettings:
        """Return scheduler settings grouped by domain."""
        return SchedulerSettings(
            enabled=self.scheduler_enabled,
            interval_internet_seconds=self.scheduler_interval_internet_seconds,
            interval_device_seconds=self.scheduler_interval_device_seconds,
            interval_server_seconds=self.scheduler_interval_server_seconds,
            interval_mikrotik_seconds=self.scheduler_interval_mikrotik_seconds,
            interval_alert_seconds=self.scheduler_interval_alert_seconds,
            cleanup_interval_hours=self.scheduler_cleanup_interval_hours,
            job_max_instances=self.scheduler_job_max_instances,
            timezone=self.scheduler_timezone,
            job_stale_factor=self.scheduler_job_stale_factor,
        )

    @property
    def internet(self) -> InternetCheckSettings:
        """Return internet check settings grouped by domain."""
        return InternetCheckSettings(
            dns_host=self.dns_check_host,
            http_url=self.http_check_url,
            http_timeout_seconds=self.http_check_timeout_seconds,
            http_retries=self.http_check_retries,
            public_ip_url=self.public_ip_check_url,
        )

    @property
    def retention(self) -> RetentionSettings:
        """Return retention settings grouped by domain."""
        return RetentionSettings(
            raw_metric_days=self.raw_metric_retention_days,
            rollup_batch_size=self.retention_rollup_batch_size,
            archive_batch_size=self.retention_archive_batch_size,
            alert_days=self.alert_retention_days,
            incident_days=self.incident_retention_days,
        )

    @property
    def dashboard(self) -> DashboardSettings:
        """Return dashboard-facing settings grouped by domain."""
        return DashboardSettings(
            api_url=self.dashboard_api_url,
            overview_cache_ttl_seconds=self.dashboard_overview_cache_ttl_seconds,
        )

    @property
    def observability(self) -> ObservabilitySettings:
        """Return observability settings grouped by domain."""
        return ObservabilitySettings(
            enable_metrics=self.observability_enable_metrics,
            log_as_json=self.log_as_json,
            request_slow_log_threshold_ms=self.request_slow_log_threshold_ms,
        )

    @property
    def thresholds(self) -> ThresholdSettings:
        """Return threshold defaults grouped by domain."""
        return ThresholdSettings(
            cpu_warning=self.cpu_warning_threshold,
            ram_warning=self.ram_warning_threshold,
            disk_warning=self.disk_warning_threshold,
        )

    @property
    def auth(self) -> AuthSettings:
        """Return authentication and authorization settings grouped by domain."""
        return AuthSettings(
            internal_api_key=self.internal_api_key,
            internal_api_keys=self.internal_api_keys,
            password_secret=self.auth_password_secret,
            token_ttl_minutes=self.auth_token_ttl_minutes,
            remember_ttl_minutes=self.auth_remember_ttl_minutes,
            jwt_secret=self.auth_jwt_secret,
            jwt_issuer=self.auth_jwt_issuer,
            jwt_algorithm=self.auth_jwt_algorithm,
            cookie_name=self.auth_cookie_name,
            refresh_cookie_name=self.auth_refresh_cookie_name,
            cookie_secure=self.auth_cookie_secure,
            cookie_samesite=self.auth_cookie_samesite,
            login_rate_limit_max_attempts=self.auth_login_rate_limit_max_attempts,
            login_rate_limit_window_minutes=self.auth_login_rate_limit_window_minutes,
            session_touch_interval_seconds=self.auth_session_touch_interval_seconds,
            session_retention_days=self.auth_session_retention_days,
            login_attempt_retention_days=self.auth_login_attempt_retention_days,
            password_min_length=self.auth_password_min_length,
            bootstrap_admin_username=self.bootstrap_admin_username,
            bootstrap_admin_full_name=self.bootstrap_admin_full_name,
            bootstrap_admin_password=self.bootstrap_admin_password,
            allow_insecure_no_auth=self.allow_insecure_no_auth,
        )

    @property
    def network_security(self) -> NetworkSecuritySettings:
        """Return network security settings grouped by domain."""
        return NetworkSecuritySettings(
            cors_origins=self.cors_origins,
            trusted_hosts=self.trusted_hosts,
            trusted_proxy_ips=self.trusted_proxy_ips,
        )

    @property
    def snmp(self) -> SnmpSettings:
        """Return SNMP community settings grouped by domain."""
        return SnmpSettings(
            printer_communities=self.printer_snmp_communities,
            nas_communities=self.nas_snmp_communities,
        )

    @property
    def normalized_cors_origins(self) -> list[str]:
        """Return CORS origins without trailing slashes."""
        return [item.rstrip("/") for item in _split_csv(self.network_security.cors_origins)]

    @property
    def normalized_trusted_hosts(self) -> list[str]:
        """Return trusted hostnames including local test and dashboard API hosts."""
        hosts = set(_split_csv(self.network_security.trusted_hosts))
        hosts.update({"localhost", "127.0.0.1", "testserver"})
        dashboard_api_url = self.dashboard.api_url
        api_host = urlparse(dashboard_api_url if "://" in dashboard_api_url else f"http://{dashboard_api_url}")
        if api_host.hostname:
            hosts.add(api_host.hostname)
        return sorted(hosts)

    @property
    def normalized_trusted_proxy_ips(self) -> set[str]:
        """Return configured trusted proxy IP addresses as a set."""
        return set(_split_csv(self.network_security.trusted_proxy_ips))

    @property
    def normalized_auth_cookie_samesite(self) -> Literal["lax", "strict", "none"]:
        """Return a safe SameSite value for auth cookies."""
        value = str(self.auth.cookie_samesite or "lax").strip().lower()
        if value == "strict":
            return "strict"
        if value == "none":
            return "none"
        return "lax"

    @property
    def normalized_mikrotik_dynamic_sections(self) -> set[str]:
        """Return enabled Mikrotik dynamic metric sections with defaults."""
        sections = {item.lower() for item in _split_csv(self.mikrotik.dynamic_sections)}
        return sections or {"interface", "firewall", "queue"}

    @property
    def normalized_mikrotik_dynamic_firewall_sections(self) -> set[str]:
        """Return enabled Mikrotik firewall subsections for dynamic metrics."""
        sections = {item.lower() for item in _split_csv(self.mikrotik.dynamic_firewall_section_allowlist)}
        return sections or {"filter", "nat"}

    @property
    def normalized_mikrotik_interface_allowlist(self) -> set[str]:
        """Return lowercase interface names allowed for dynamic Mikrotik metrics."""
        return {item.lower() for item in _split_csv(self.mikrotik.dynamic_interface_allowlist)}

    @property
    def normalized_mikrotik_queue_allowlist(self) -> set[str]:
        """Return lowercase simple-queue names allowed for dynamic Mikrotik metrics."""
        return {item.lower() for item in _split_csv(self.mikrotik.dynamic_queue_allowlist)}

    @property
    def is_production(self) -> bool:
        """Return True when APP_ENV is production."""
        return self.app.is_production

    @property
    def is_development(self) -> bool:
        """Return True when running in local development mode."""
        return self.app.is_development


settings = Settings()


def printer_snmp_community_map() -> dict[str, str]:
    """Return printer snmp community map for configuration, time, or security helpers."""
    return _parse_printer_snmp_community_map(settings.snmp.printer_communities or "")


def nas_snmp_community_map() -> dict[str, str]:
    """Return NAS snmp community map for configuration helpers."""
    return _parse_printer_snmp_community_map(settings.snmp.nas_communities or "")


@lru_cache(maxsize=8)
def _parse_printer_snmp_community_map(raw_value: str) -> dict[str, str]:
    """Parse printer snmp community map for configuration, time, or security helpers."""
    raw_value = raw_value.strip()
    if not raw_value:
        return {}

    if raw_value.startswith("{"):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            return {
                str(ip_address).strip(): str(community).strip()
                for ip_address, community in parsed.items()
                if str(ip_address).strip() and str(community).strip()
            }

    community_map: dict[str, str] = {}
    normalized_value = raw_value.replace("\r", "\n").replace(",", "\n")
    for line in normalized_value.splitlines():
        item = line.strip()
        if not item or "=" not in item:
            continue
        ip_address, community = item.split("=", 1)
        ip_address = ip_address.strip()
        community = community.strip()
        if ip_address and community:
            community_map[ip_address] = community
    return community_map


def printer_snmp_community_for_ip(ip_address: str) -> str | None:
    """Return printer snmp community for ip for configuration, time, or security helpers."""
    return printer_snmp_community_map().get(str(ip_address).strip())


def nas_snmp_community_for_ip(ip_address: str) -> str | None:
    """Return NAS snmp community for ip for configuration helpers."""
    return nas_snmp_community_map().get(str(ip_address).strip())


@lru_cache(maxsize=4)
def _parse_internal_api_key_map(raw_keys: str, legacy_key: str) -> dict[str, dict[str, object]]:
    """Parse internal api key map for configuration, time, or security helpers."""
    payload: dict[str, dict[str, object]] = {}
    normalized_raw = str(raw_keys or "").strip()
    if normalized_raw:
        if normalized_raw.startswith("{"):
            try:
                parsed = json.loads(normalized_raw)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                for key_name, item in parsed.items():
                    if not isinstance(item, dict):
                        continue
                    secret = str(item.get("key") or "").strip()
                    scopes = [str(scope).strip().lower() for scope in item.get("scopes", []) if str(scope).strip()]
                    if secret and scopes:
                        payload[secret] = {"name": str(key_name).strip() or "unnamed", "scopes": sorted(set(scopes))}
        else:
            for raw_line in normalized_raw.replace("\r", "\n").splitlines():
                item = raw_line.strip()
                if not item:
                    continue
                parts = [part.strip() for part in item.split(":", 2)]
                if len(parts) != 3:
                    continue
                key_name, secret, scopes_raw = parts
                scopes = [scope.strip().lower() for scope in scopes_raw.split(",") if scope.strip()]
                if secret and scopes:
                    payload[secret] = {"name": key_name or "unnamed", "scopes": sorted(set(scopes))}
    legacy_key = str(legacy_key or "").strip()
    if legacy_key and legacy_key not in payload:
        payload[legacy_key] = {"name": "legacy-default", "scopes": ["ops", "read", "write"]}
    return payload


def internal_api_key_map() -> dict[str, dict[str, object]]:
    """Return internal api key map for configuration, time, or security helpers."""
    return _parse_internal_api_key_map(settings.auth.internal_api_keys or "", settings.auth.internal_api_key or "")


def configure_logging() -> None:
    """Configure logging for configuration, time, or security helpers."""
    logging.basicConfig(
        level=getattr(logging, settings.app.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    from ..services.observability_service import configure_structured_logging

    configure_structured_logging()
