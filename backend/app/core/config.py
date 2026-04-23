"""Provide application-wide configuration, constants, security, and time helpers for the network monitoring project."""

import json
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(raw_value: str) -> list[str]:
    return [item.strip() for item in str(raw_value or "").split(",") if item.strip()]


class Settings(BaseSettings):
    app_name: str = "Network Monitoring"
    app_env: str = "development"
    database_url: str = "mysql+pymysql://network_monitoring:change-me@localhost:3306/network_monitoring"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
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
    monitoring_lock_name: str = "network_monitoring.pipeline"
    monitoring_lock_timeout_seconds: int = 900
    dns_check_host: str = "google.com"
    http_check_url: str = "https://www.google.com/generate_204"
    public_ip_check_url: str = "https://api.ipify.org"
    raw_metric_retention_days: int = 7
    retention_rollup_batch_size: int = 500
    retention_archive_batch_size: int = 500
    alert_retention_days: int = 180
    incident_retention_days: int = 180
    scheduler_cleanup_interval_hours: int = 24
    scheduler_job_stale_factor: int = 3
    observability_enable_metrics: bool = True
    log_as_json: bool = True
    request_slow_log_threshold_ms: int = 1000
    cpu_warning_threshold: float = 90.0
    ram_warning_threshold: float = 90.0
    disk_warning_threshold: float = 85.0
    internal_api_key: str = ""
    internal_api_keys: str = ""
    auth_password_secret: str = ""
    printer_snmp_communities: str = ""
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
    bootstrap_admin_password_file: str | None = None
    auth_jwt_secret_file: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def load_file_backed_secrets(self) -> "Settings":
        secret_fields = {
            "telegram_bot_token": self.telegram_bot_token_file,
            "telegram_chat_id": self.telegram_chat_id_file,
            "mikrotik_password": self.mikrotik_password_file,
            "internal_api_key": self.internal_api_key_file,
            "auth_password_secret": self.auth_password_secret_file,
            "printer_snmp_communities": self.printer_snmp_communities_file,
            "bootstrap_admin_password": self.bootstrap_admin_password_file,
            "auth_jwt_secret": self.auth_jwt_secret_file,
        }
        for field_name, raw_file_path in secret_fields.items():
            if not raw_file_path:
                continue
            file_path = Path(raw_file_path)
            object.__setattr__(self, field_name, file_path.read_text(encoding="utf-8").strip())
        return self

    @property
    def normalized_cors_origins(self) -> list[str]:
        return [item.rstrip("/") for item in _split_csv(self.cors_origins)]

    @property
    def normalized_trusted_hosts(self) -> list[str]:
        hosts = set(_split_csv(self.trusted_hosts))
        hosts.update({"localhost", "127.0.0.1", "testserver"})
        api_host = urlparse(self.dashboard_api_url if "://" in self.dashboard_api_url else f"http://{self.dashboard_api_url}")
        if api_host.hostname:
            hosts.add(api_host.hostname)
        return sorted(hosts)

    @property
    def normalized_trusted_proxy_ips(self) -> set[str]:
        return set(_split_csv(self.trusted_proxy_ips))

    @property
    def normalized_auth_cookie_samesite(self) -> str:
        allowed = {"lax", "strict", "none"}
        value = str(self.auth_cookie_samesite or "lax").strip().lower()
        return value if value in allowed else "lax"

    @property
    def normalized_mikrotik_dynamic_sections(self) -> set[str]:
        sections = {item.lower() for item in _split_csv(self.mikrotik_dynamic_sections)}
        return sections or {"interface", "firewall", "queue"}

    @property
    def normalized_mikrotik_dynamic_firewall_sections(self) -> set[str]:
        sections = {item.lower() for item in _split_csv(self.mikrotik_dynamic_firewall_section_allowlist)}
        return sections or {"filter", "nat"}

    @property
    def normalized_mikrotik_interface_allowlist(self) -> set[str]:
        return {item.lower() for item in _split_csv(self.mikrotik_dynamic_interface_allowlist)}

    @property
    def normalized_mikrotik_queue_allowlist(self) -> set[str]:
        return {item.lower() for item in _split_csv(self.mikrotik_dynamic_queue_allowlist)}

    @property
    def is_production(self) -> bool:
        return str(self.app_env or "").strip().lower() == "production"


settings = Settings()


def printer_snmp_community_map() -> dict[str, str]:
    return _parse_printer_snmp_community_map(settings.printer_snmp_communities or "")


@lru_cache(maxsize=8)
def _parse_printer_snmp_community_map(raw_value: str) -> dict[str, str]:
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
    return printer_snmp_community_map().get(str(ip_address).strip())


@lru_cache(maxsize=4)
def _parse_internal_api_key_map(raw_keys: str, legacy_key: str) -> dict[str, dict[str, object]]:
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
    return _parse_internal_api_key_map(settings.internal_api_keys or "", settings.internal_api_key or "")


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    from ..services.observability_service import configure_structured_logging

    configure_structured_logging()
