"""FastAPI routes for metrics endpoints."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import (
    MetricDailySummaryPage,
    MetricHistoryContextPayload,
    MetricHistoryCursorPage,
    MetricHistoryItem,
    MetricHistoryPage,
)
from ...api.lifecycle import apply_legacy_deprecation_headers
from ...db.session import get_db
from ...services import metrics_read_service

router = APIRouter()


@router.get("/names", response_model=list[str])
async def get_metric_names(
    device_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Return metric names currently present in latest snapshots."""
    return await metrics_read_service.list_metric_names(db, device_id=device_id)


@router.get("/history", response_model=list[MetricHistoryItem], deprecated=True)
async def get_metrics_history(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[MetricHistoryItem]:
    """Return legacy metric history rows."""
    apply_legacy_deprecation_headers(response, legacy_endpoint="/metrics/history")
    return await metrics_read_service.get_metrics_history(
        db,
        limit=limit,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )


@router.get("/history/paged", response_model=MetricHistoryCursorPage)
async def get_metrics_history_paged(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    metric_names: list[str] | None = Query(default=None),
    per_metric_limit: int | None = Query(default=None, ge=1, le=500),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MetricHistoryCursorPage:
    """Return paginated metric history rows."""
    return await metrics_read_service.get_metrics_history_page(
        db,
        limit=limit,
        offset=offset,
        cursor=cursor,
        device_id=device_id,
        metric_name=metric_name,
        metric_names=metric_names,
        per_metric_limit=per_metric_limit,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )


@router.get("/history/context", response_model=MetricHistoryContextPayload)
async def get_metrics_history_context(
    limit: int = Query(default=100, ge=1, le=500),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    selected_device_limit: int = Query(default=200, ge=1, le=500),
    selected_device_offset: int = Query(default=0, ge=0),
    include_selected_device_trend: bool = Query(default=False),
    trend_metric_names: list[str] | None = Query(default=None),
    trend_limit: int = Query(default=200, ge=1, le=2000),
    snapshot_limit: int = Query(default=10, ge=1, le=500),
    snapshot_offset: int = Query(default=0, ge=0),
    include_selected_device_snapshot: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> MetricHistoryContextPayload:
    """Return dashboard history context payload."""
    return await metrics_read_service.get_metrics_history_context(
        db,
        limit=limit,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
        selected_device_limit=selected_device_limit,
        selected_device_offset=selected_device_offset,
        include_selected_device_trend=include_selected_device_trend,
        trend_metric_names=trend_metric_names,
        trend_limit=trend_limit,
        snapshot_limit=snapshot_limit,
        snapshot_offset=snapshot_offset,
        include_selected_device_snapshot=include_selected_device_snapshot,
    )


@router.get("/history/live", response_model=MetricHistoryContextPayload)
async def get_metrics_history_live(
    limit: int = Query(default=100, ge=1, le=500),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    selected_device_limit: int = Query(default=200, ge=1, le=500),
    include_selected_device_trend: bool = Query(default=False),
    trend_metric_names: list[str] | None = Query(default=None),
    trend_limit: int = Query(default=200, ge=1, le=2000),
    snapshot_limit: int = Query(default=10, ge=1, le=500),
    snapshot_offset: int = Query(default=0, ge=0),
    include_selected_device_snapshot: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> MetricHistoryContextPayload:
    """Return lightweight live dashboard history payload."""
    _ = (checked_from, checked_to)
    return await metrics_read_service.get_metrics_history_live(
        db,
        limit=limit,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        selected_device_limit=selected_device_limit,
        include_selected_device_trend=include_selected_device_trend,
        trend_metric_names=trend_metric_names,
        trend_limit=trend_limit,
        snapshot_limit=snapshot_limit,
        snapshot_offset=snapshot_offset,
        include_selected_device_snapshot=include_selected_device_snapshot,
    )


@router.get("/daily-summary", response_model=MetricDailySummaryPage)
async def get_metrics_daily_summary(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    device_id: int | None = Query(default=None),
    rollup_from: date | None = Query(default=None),
    rollup_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MetricDailySummaryPage:
    """Return paginated daily metric rollup rows."""
    return await metrics_read_service.get_metrics_daily_summary(
        db,
        limit=limit,
        offset=offset,
        device_id=device_id,
        rollup_from=rollup_from,
        rollup_to=rollup_to,
    )


@router.get("/latest-snapshot/paged", response_model=MetricHistoryPage)
async def get_latest_metrics_snapshot_paged(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    device_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MetricHistoryPage:
    """Return paginated latest metric snapshot rows."""
    return await metrics_read_service.get_latest_metrics_snapshot_page(
        db,
        limit=limit,
        offset=offset,
        cursor=cursor,
        device_id=device_id,
    )


@router.get("/latest-snapshot/status-summary", response_model=dict[str, int])
async def get_latest_snapshot_status_summary(
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Return latest-snapshot status summary."""
    return await metrics_read_service.get_latest_snapshot_status_summary(db)


@router.get("/latest-snapshot/uptime-map", response_model=dict[str, str])
async def get_latest_snapshot_uptime_map(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Return latest-snapshot uptime map."""
    return await metrics_read_service.get_latest_snapshot_uptime_map(db, limit=limit, offset=offset)
