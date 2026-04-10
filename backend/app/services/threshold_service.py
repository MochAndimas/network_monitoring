from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.config import settings
from ..repositories.threshold_repository import ThresholdRepository


DEFAULT_THRESHOLDS = {
    "ping_latency_warning": (100.0, "Ping latency warning threshold in milliseconds"),
    "ping_latency_critical": (200.0, "Ping latency critical threshold in milliseconds"),
    "cpu_warning": (settings.cpu_warning_threshold, "CPU usage warning threshold in percent"),
    "ram_warning": (settings.ram_warning_threshold, "Memory usage warning threshold in percent"),
    "disk_warning": (settings.disk_warning_threshold, "Disk usage warning threshold in percent"),
    "packet_loss_warning": (20.0, "Packet loss threshold in percent"),
    "packet_loss_critical": (50.0, "Critical packet loss threshold in percent"),
    "jitter_warning": (30.0, "Jitter warning threshold in milliseconds"),
    "jitter_critical": (75.0, "Critical jitter threshold in milliseconds"),
    "dns_resolution_warning": (500.0, "DNS resolution warning threshold in milliseconds"),
    "http_response_warning": (1000.0, "HTTP response warning threshold in milliseconds"),
}


def ensure_default_thresholds(db: Session) -> list:
    repository = ThresholdRepository(db)
    thresholds = []
    for key, (value, description) in DEFAULT_THRESHOLDS.items():
        existing = repository.get_by_key(key)
        if existing is None:
            thresholds.append(repository.upsert_threshold(key, value, description))
        else:
            thresholds.append(existing)
    return thresholds


def list_threshold_rows(db: Session) -> list[dict]:
    ensure_default_thresholds(db)
    return [
        {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}
        for threshold in ThresholdRepository(db).list_thresholds()
    ]


def get_threshold_map(db: Session) -> dict[str, float]:
    ensure_default_thresholds(db)
    return {threshold.key: threshold.value for threshold in ThresholdRepository(db).list_thresholds()}


def update_threshold_value(db: Session, key: str, value: float) -> dict:
    if key not in DEFAULT_THRESHOLDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Threshold not found")
    _, description = DEFAULT_THRESHOLDS[key]
    threshold = ThresholdRepository(db).upsert_threshold(key, value, description)
    return {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}
