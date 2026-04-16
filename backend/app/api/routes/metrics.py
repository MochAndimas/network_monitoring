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
    return _metric_history_response_items(metrics)


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
    repository = MetricRepository(db)
    metrics, total = await repository.list_recent_metric_rows_paged(
        limit=limit,
        offset=offset,
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


@router.get("/history/context")
async def get_metrics_history_context(
    limit: int = Query(default=100, ge=1, le=500),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    snapshot_limit: int = Query(default=10, ge=1, le=500),
    snapshot_offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repository = MetricRepository(db)
    history_rows, history_total = await repository.list_recent_metric_rows_paged(
        limit=limit,
        offset=0,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )
    selected_device_history_rows = []
    if device_id is not None:
        selected_device_history_rows = await _list_all_recent_metric_rows(
            repository,
            device_id=device_id,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
    latest_snapshot_rows, latest_snapshot_total = await repository.list_latest_metric_rows_paged(
        limit=snapshot_limit,
        offset=snapshot_offset,
    )
    return {
        "metric_names": await repository.list_metric_names(device_id=device_id),
        "history": {
            "items": _metric_history_dicts(history_rows),
            "meta": {"total": history_total, "limit": limit, "offset": 0},
        },
        "selected_device_history": _metric_history_dicts(selected_device_history_rows),
        "latest_snapshot": {
            "items": _metric_history_dicts(latest_snapshot_rows),
            "meta": {"total": latest_snapshot_total, "limit": snapshot_limit, "offset": snapshot_offset},
        },
        "latest_snapshot_status_summary": await repository.summarize_latest_snapshot_status_counts(),
        "snapshot_uptime_map": await repository.latest_snapshot_uptime_map_for_rows(latest_snapshot_rows),
    }


@router.get("/latest-snapshot/paged", response_model=MetricHistoryPage)
async def get_latest_metrics_snapshot_paged(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> MetricHistoryPage:
    repository = MetricRepository(db)
    metrics, total = await repository.list_latest_metric_rows_paged(limit=limit, offset=offset)
    return MetricHistoryPage(
        items=_metric_history_response_items(metrics),
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/latest-snapshot/status-summary", response_model=dict[str, int])
async def get_latest_snapshot_status_summary(
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    return await MetricRepository(db).summarize_latest_snapshot_status_counts()


@router.get("/latest-snapshot/uptime-map", response_model=dict[str, str])
async def get_latest_snapshot_uptime_map(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    return await MetricRepository(db).latest_snapshot_uptime_map(limit=limit, offset=offset)


def _metric_history_response_items(metrics: list[dict]) -> list[MetricHistoryItem]:
    return [MetricHistoryItem(**metric) for metric in _metric_history_dicts(metrics)]


def _metric_history_dicts(metrics: list[dict]) -> list[dict]:
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
        for metric in metrics
    ]


async def _list_all_recent_metric_rows(
    repository: MetricRepository,
    *,
    device_id: int,
    status: str | None,
    checked_from: datetime | None,
    checked_to: datetime | None,
) -> list[dict]:
    page_size = 500
    offset = 0
    payload: list[dict] = []
    while True:
        rows = await repository.list_recent_metric_rows(
            limit=page_size,
            offset=offset,
            device_id=device_id,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        if not rows:
            break
        payload.extend(rows)
        if len(rows) < page_size:
            break
        offset += len(rows)
    return payload
