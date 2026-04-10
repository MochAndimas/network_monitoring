from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.metric_repository import MetricRepository


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def persist_metrics(db: Session, metrics: list[dict]) -> list:
    return MetricRepository(db).create_metrics(metrics)


def latest_metric_snapshot(db: Session) -> dict[tuple[int, str], object]:
    return MetricRepository(db).latest_metric_map()


def status_rollup(statuses: list[str]) -> str:
    if not statuses:
        return "unknown"
    if any(status in {"down", "critical", "error"} for status in statuses):
        return "down"
    if any(status in {"warning", "degraded", "unavailable"} for status in statuses):
        return "warning"
    if all(status in {"up", "healthy", "ok"} for status in statuses):
        return "up"
    return statuses[0]


def build_device_status_rows(db: Session) -> list[dict]:
    devices = DeviceRepository(db).list_devices(active_only=False)
    latest_metrics = latest_metric_snapshot(db)

    rows: list[dict] = []
    for device in devices:
        ping_metric = latest_metrics.get((device.id, "ping"))
        rows.append(
            {
                "id": device.id,
                "name": device.name,
                "ip_address": device.ip_address,
                "device_type": device.device_type,
                "site": device.site,
                "description": device.description,
                "is_active": device.is_active,
                "latest_status": getattr(ping_metric, "status", None) or "unknown",
                "latest_checked_at": getattr(ping_metric, "checked_at", None),
            }
        )
    return rows


def build_dashboard_summary(db: Session) -> dict:
    devices = DeviceRepository(db).list_devices(active_only=True)
    latest_metrics = latest_metric_snapshot(db)

    grouped_statuses: dict[str, list[str]] = defaultdict(list)
    for device in devices:
        metric = latest_metrics.get((device.id, "ping"))
        if metric is not None:
            grouped_statuses[device.device_type].append(metric.status or "unknown")

    return {
        "internet_status": status_rollup(grouped_statuses.get("internet_target", [])),
        "mikrotik_status": status_rollup(grouped_statuses.get("mikrotik", [])),
        "server_status": status_rollup(grouped_statuses.get("server", [])),
        "active_alerts": AlertRepository(db).count_active_alerts(),
    }
