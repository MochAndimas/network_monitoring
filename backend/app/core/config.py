import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Network Monitoring"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+psycopg://network_monitoring:change-me@localhost:5432/network_monitoring"
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
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
