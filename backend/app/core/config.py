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
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    mikrotik_host: str = ""
    mikrotik_username: str = ""
    mikrotik_password: str = ""
    dashboard_api_url: str = "http://localhost:8000"
    ping_timeout_seconds: float = 2.0
    ping_sample_count: int = 3
    ping_concurrency_limit: int = 32
    scheduler_enabled: bool = True
    scheduler_interval_internet_seconds: int = 30
    scheduler_interval_device_seconds: int = 60
    scheduler_interval_server_seconds: int = 60
    scheduler_interval_mikrotik_seconds: int = 60
    scheduler_interval_alert_seconds: int = 30
    scheduler_job_max_instances: int = 1
    dns_check_host: str = "google.com"
    http_check_url: str = "https://www.google.com/generate_204"
    public_ip_check_url: str = "https://api.ipify.org"
    raw_metric_retention_days: int = 7
    alert_retention_days: int = 180
    incident_retention_days: int = 180
    scheduler_cleanup_interval_hours: int = 24
    cpu_warning_threshold: float = 90.0
    ram_warning_threshold: float = 90.0
    disk_warning_threshold: float = 85.0
    internal_api_key: str = ""
    printer_snmp_communities: str = ""
    auth_token_ttl_minutes: int = 720
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_full_name: str = "Monitoring Admin"
    bootstrap_admin_password: str = ""
    allow_insecure_no_auth: bool = False
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    trusted_hosts: str = "localhost,127.0.0.1"
    log_level: str = "INFO"
    telegram_bot_token_file: str | None = None
    telegram_chat_id_file: str | None = None
    mikrotik_password_file: str | None = None
    internal_api_key_file: str | None = None
    printer_snmp_communities_file: str | None = None
    bootstrap_admin_password_file: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def load_file_backed_secrets(self) -> "Settings":
        secret_fields = {
            "telegram_bot_token": self.telegram_bot_token_file,
            "telegram_chat_id": self.telegram_chat_id_file,
            "mikrotik_password": self.mikrotik_password_file,
            "internal_api_key": self.internal_api_key_file,
            "printer_snmp_communities": self.printer_snmp_communities_file,
            "bootstrap_admin_password": self.bootstrap_admin_password_file,
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


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
