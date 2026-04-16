import logging
import json
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


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
