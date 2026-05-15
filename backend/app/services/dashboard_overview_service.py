"""Cached read model for dashboard overview payloads."""

from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..repositories.alert_repository import AlertRepository
from ..repositories.device_repository import DeviceRepository
from ..repositories.incident_repository import IncidentRepository
from ..repositories.metric_repository import MetricRepository
from .monitoring_service import build_dashboard_summary

_overview_cache: dict[tuple[int, int, int, bool, int], tuple[float, dict[str, Any]]] = {}
_overview_cache_generation = 0


def invalidate_dashboard_overview_cache() -> None:
    """Invalidate cached overview payloads after monitoring or inventory writes."""
    global _overview_cache_generation
    _overview_cache_generation += 1
    _overview_cache.clear()


async def get_overview_payload(
    db: AsyncSession,
    *,
    snapshot_limit: int,
    alerts_limit: int,
    incidents_limit: int,
    include_problem_devices: bool = False,
) -> dict:
    """Return an overview payload, using a short-lived backend cache for refresh-heavy callers."""
    cache_key = (snapshot_limit, alerts_limit, incidents_limit, include_problem_devices, _overview_cache_generation)
    cached = _overview_cache.get(cache_key)
    now = monotonic()
    if cached is not None:
        expires_at, payload = cached
        if expires_at > now:
            return deepcopy(payload)
        _overview_cache.pop(cache_key, None)

    payload = await _build_overview_payload(
        db,
        snapshot_limit=snapshot_limit,
        alerts_limit=alerts_limit,
        incidents_limit=incidents_limit,
        include_problem_devices=include_problem_devices,
    )
    ttl_seconds = max(float(settings.dashboard.overview_cache_ttl_seconds), 0.0)
    if ttl_seconds > 0:
        _overview_cache[cache_key] = (now + ttl_seconds, deepcopy(payload))
    return payload


async def _build_overview_payload(
    db: AsyncSession,
    *,
    snapshot_limit: int,
    alerts_limit: int,
    incidents_limit: int,
    include_problem_devices: bool,
) -> dict:
    """Build the dashboard overview payload from repositories."""
    device_repository = DeviceRepository(db)
    metric_repository = MetricRepository(db)
    alert_repository = AlertRepository(db)
    incident_repository = IncidentRepository(db)
    summary = await build_dashboard_summary(db)
    latest_snapshot_rows, latest_snapshot_total = await metric_repository.list_latest_metric_rows_paged(
        limit=snapshot_limit,
        offset=0,
    )
    device_status_summary = await device_repository.summarize_device_status_counts(active_only=True)
    total_devices = await device_repository.count_devices(active_only=False)
    active_devices = await device_repository.count_devices(active_only=True)
    payload = {
        "summary": summary,
        "device_counts": {
            "total": total_devices,
            "active": active_devices,
            "inactive": max(total_devices - active_devices, 0),
            "statuses": device_status_summary,
            "latest_check_at": await device_repository.latest_device_check_at(active_only=True),
        },
        "alert_severity_summary": await alert_repository.summarize_active_alert_severity_counts(),
        "alerts": await alert_repository.list_active_alert_rows(limit=alerts_limit),
        "incidents": await incident_repository.list_incident_rows(status="active", limit=incidents_limit),
        "latest_snapshot": {
            "items": _metric_history_items(latest_snapshot_rows),
            "meta": {"total": latest_snapshot_total, "limit": snapshot_limit, "offset": 0},
        },
    }
    if include_problem_devices:
        payload["problem_devices"] = await get_problem_device_rows(db, limit=25)
    return payload


async def get_problem_device_rows(db: AsyncSession, *, limit: int) -> list[dict]:
    """Return active devices whose latest health status needs attention."""
    return await DeviceRepository(db).list_device_status_rows(
        active_only=True,
        latest_status=["down", "warning", "error"],
        limit=limit,
        offset=0,
    )


def _metric_history_items(rows: list[dict]) -> list[dict]:
    """Convert metric rows into the overview response item shape."""
    return [
        {
            "id": metric["id"],
            "device_id": metric["device_id"],
            "device_name": metric["device_name"],
            "metric_name": metric["metric_name"],
            "metric_value": metric["metric_value"],
            "metric_value_numeric": metric["metric_value_numeric"],
            "status": metric["status"],
            "unit": metric["unit"],
            "checked_at": metric["checked_at"],
        }
        for metric in rows
    ]


__all__ = [
    "get_overview_payload",
    "get_problem_device_rows",
    "invalidate_dashboard_overview_cache",
]
