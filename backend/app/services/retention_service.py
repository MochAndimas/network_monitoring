from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.alert import Alert
from ..models.incident import Incident
from ..models.metric import Metric
from ..models.metric_daily_rollup import MetricDailyRollup
from .monitoring_service import utcnow


UP_STATUSES = {"up", "ok"}


def cleanup_monitoring_data(db: Session) -> dict[str, int]:
    rolled_up_days = rollup_completed_raw_metrics(db)
    deleted_metrics = delete_expired_raw_metrics(db)
    deleted_alerts = delete_expired_alerts(db)
    deleted_incidents = delete_expired_incidents(db)
    return {
        "rolled_up_days": rolled_up_days,
        "deleted_metrics": deleted_metrics,
        "deleted_alerts": deleted_alerts,
        "deleted_incidents": deleted_incidents,
    }


def rollup_completed_raw_metrics(db: Session) -> int:
    cutoff = _today_start()
    metrics = list(db.scalars(select(Metric).where(Metric.checked_at < cutoff)).all())
    grouped_metrics: dict[tuple[int, object], list[Metric]] = defaultdict(list)
    for metric in metrics:
        grouped_metrics[(metric.device_id, metric.checked_at.date())].append(metric)

    now = utcnow()
    for (device_id, rollup_date), rows in grouped_metrics.items():
        payload = _build_daily_rollup(device_id, rollup_date, rows, now)
        existing = db.scalars(
            select(MetricDailyRollup).where(
                MetricDailyRollup.device_id == device_id,
                MetricDailyRollup.rollup_date == rollup_date,
            )
        ).first()
        if existing is None:
            db.add(MetricDailyRollup(**payload))
            continue

        for key, value in payload.items():
            setattr(existing, key, value)

    db.commit()
    return len(grouped_metrics)


def delete_expired_raw_metrics(db: Session) -> int:
    result = db.execute(delete(Metric).where(Metric.checked_at < _raw_metric_cutoff()))
    db.commit()
    return int(result.rowcount or 0)


def delete_expired_alerts(db: Session) -> int:
    cutoff = utcnow() - timedelta(days=settings.alert_retention_days)
    result = db.execute(
        delete(Alert).where(
            Alert.status != "active",
            or_(
                Alert.resolved_at < cutoff,
                and_(Alert.resolved_at.is_(None), Alert.created_at < cutoff),
            ),
        )
    )
    db.commit()
    return int(result.rowcount or 0)


def delete_expired_incidents(db: Session) -> int:
    cutoff = utcnow() - timedelta(days=settings.incident_retention_days)
    result = db.execute(
        delete(Incident).where(
            Incident.status != "active",
            or_(
                Incident.ended_at < cutoff,
                and_(Incident.ended_at.is_(None), Incident.started_at < cutoff),
            ),
        )
    )
    db.commit()
    return int(result.rowcount or 0)


def _raw_metric_cutoff() -> datetime:
    cutoff_date = (utcnow() - timedelta(days=settings.raw_metric_retention_days)).date()
    return datetime.combine(cutoff_date, time.min)


def _today_start() -> datetime:
    return datetime.combine(utcnow().date(), time.min)


def _build_daily_rollup(device_id: int, rollup_date, rows: list[Metric], now) -> dict:
    ping_rows = [row for row in rows if row.metric_name == "ping"]
    ping_values = [_safe_float(row.metric_value) for row in ping_rows]
    ping_values = [value for value in ping_values if value is not None]
    packet_loss_values = _numeric_values(rows, "packet_loss")
    jitter_values = _numeric_values(rows, "jitter")
    ping_statuses = [str(row.status or "").lower() for row in ping_rows]
    ping_count = len(ping_statuses)
    uptime_count = sum(1 for status in ping_statuses if status in UP_STATUSES)

    return {
        "device_id": device_id,
        "rollup_date": rollup_date,
        "total_samples": len(rows),
        "ping_samples": ping_count,
        "down_count": sum(1 for status in ping_statuses if status == "down"),
        "uptime_percentage": (uptime_count / ping_count) * 100 if ping_count else None,
        "average_ping_ms": _average(ping_values),
        "min_ping_ms": min(ping_values) if ping_values else None,
        "max_ping_ms": max(ping_values) if ping_values else None,
        "average_packet_loss_percent": _average(packet_loss_values),
        "average_jitter_ms": _average(jitter_values),
        "max_jitter_ms": max(jitter_values) if jitter_values else None,
        "updated_at": now,
    }


def _numeric_values(rows: list[Metric], metric_name: str) -> list[float]:
    values = [_safe_float(row.metric_value) for row in rows if row.metric_name == metric_name]
    return [value for value in values if value is not None]


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
