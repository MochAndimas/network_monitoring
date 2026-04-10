from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...api.schemas import MetricHistoryItem
from ...db.session import get_db
from ...repositories.device_repository import DeviceRepository
from ...repositories.metric_repository import MetricRepository

router = APIRouter()


@router.get("/names", response_model=list[str])
async def get_metric_names(
    device_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[str]:
    return MetricRepository(db).list_metric_names(device_id=device_id)


@router.get("/history", response_model=list[MetricHistoryItem])
async def get_metrics_history(
    limit: int = Query(default=100, ge=1, le=500),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[MetricHistoryItem]:
    devices = {device.id: device for device in DeviceRepository(db).list_devices(active_only=False)}
    metrics = MetricRepository(db).list_recent_metrics(
        limit=limit,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
    )
    return [
        MetricHistoryItem(
            id=metric.id,
            device_id=metric.device_id,
            device_name=devices.get(metric.device_id).name if devices.get(metric.device_id) else "Unknown Device",
            metric_name=metric.metric_name,
            metric_value=metric.metric_value,
            metric_value_numeric=_safe_float(metric.metric_value),
            status=metric.status,
            unit=metric.unit,
            checked_at=metric.checked_at,
        )
        for metric in metrics
    ]


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
