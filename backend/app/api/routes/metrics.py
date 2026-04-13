from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import MetricHistoryItem, MetricHistoryPage, PageMeta
from ...db.session import get_db
from ...repositories.metric_repository import MetricRepository

router = APIRouter()


@router.get("/names", response_model=list[str])
async def get_metric_names(
    device_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    return await MetricRepository(db).list_metric_names(device_id=device_id)


@router.get("/history", response_model=list[MetricHistoryItem])
async def get_metrics_history(
    limit: int = Query(default=100, ge=1, le=500),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[MetricHistoryItem]:
    metrics = await MetricRepository(db).list_recent_metric_rows(
        limit=limit,
        offset=0,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )
    return [
        MetricHistoryItem(
            id=metric["id"],
            device_id=metric["device_id"],
            device_name=metric["device_name"],
            metric_name=metric["metric_name"],
            metric_value=metric["metric_value"],
            metric_value_numeric=metric["metric_value_numeric"],
            status=metric["status"],
            unit=metric["unit"],
            checked_at=metric["checked_at"],
        )
        for metric in metrics
    ]


@router.get("/history/paged", response_model=MetricHistoryPage)
async def get_metrics_history_paged(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MetricHistoryPage:
    metrics = await MetricRepository(db).list_recent_metric_rows(
        limit=limit,
        offset=offset,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )
    total = await MetricRepository(db).count_recent_metric_rows(
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )
    return MetricHistoryPage(
        items=[
            MetricHistoryItem(
                id=metric["id"],
                device_id=metric["device_id"],
                device_name=metric["device_name"],
                metric_name=metric["metric_name"],
                metric_value=metric["metric_value"],
                metric_value_numeric=metric["metric_value_numeric"],
                status=metric["status"],
                unit=metric["unit"],
                checked_at=metric["checked_at"],
            )
            for metric in metrics
        ],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )
