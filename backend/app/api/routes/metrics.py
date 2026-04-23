"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import MetricDailySummaryItem, MetricDailySummaryPage, MetricHistoryItem, MetricHistoryPage, PageMeta
from ...core.time import now
from ...db.session import get_db
from ...repositories.metric_repository import MetricRepository
from ...services.observability_service import record_api_payload_request, record_api_payload_section

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
    metric_names: list[str] | None = Query(default=None),
    per_metric_limit: int | None = Query(default=None, ge=1, le=500),
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
        metric_names=metric_names,
        per_metric_limit=per_metric_limit,
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
    selected_device_limit: int = Query(default=200, ge=1, le=500),
    selected_device_offset: int = Query(default=0, ge=0),
    snapshot_limit: int = Query(default=10, ge=1, le=500),
    snapshot_offset: int = Query(default=0, ge=0),
    include_selected_device_snapshot: bool = Query(default=False),
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
    selected_device_history_total = 0
    if device_id is not None:
        if selected_device_offset == 0 and selected_device_limit <= limit:
            selected_device_history_rows = history_rows[:selected_device_limit]
            selected_device_history_total = history_total
        else:
            selected_device_history_rows, selected_device_history_total = await repository.list_recent_metric_rows_paged(
                limit=selected_device_limit,
                offset=selected_device_offset,
                device_id=device_id,
                metric_name=metric_name,
                status=status,
                checked_from=checked_from,
                checked_to=checked_to,
            )
    latest_snapshot_rows, latest_snapshot_total = await repository.list_latest_metric_rows_paged(
        limit=snapshot_limit,
        offset=snapshot_offset,
    )
    if snapshot_offset == 0 and latest_snapshot_total <= snapshot_limit:
        latest_snapshot_status_summary = repository.summarize_latest_snapshot_status_counts_for_rows(latest_snapshot_rows)
    else:
        latest_snapshot_status_summary = await repository.summarize_latest_snapshot_status_counts()
    selected_device_snapshot_rows = []
    selected_device_snapshot_total = 0
    if include_selected_device_snapshot and device_id is not None:
        selected_device_snapshot_rows, selected_device_snapshot_total = await repository.list_latest_metric_rows_paged(
            limit=500,
            offset=0,
            device_id=device_id,
        )
    history_items = _metric_history_dicts(history_rows)
    selected_device_history_items = (
        history_items
        if selected_device_history_rows is history_rows
        else _metric_history_dicts(selected_device_history_rows)
    )
    latest_snapshot_items = _metric_history_dicts(latest_snapshot_rows)
    selected_device_snapshot_items = _metric_history_dicts(selected_device_snapshot_rows)
    payload_scope = "device" if device_id is not None else "global"
    latest_snapshot_sampled = latest_snapshot_total > len(latest_snapshot_items)
    selected_history_sampled = selected_device_history_total > len(selected_device_history_items)
    selected_snapshot_sampled = selected_device_snapshot_total > len(selected_device_snapshot_items)
    record_api_payload_request(endpoint="/metrics/history/context", scope=payload_scope)
    record_api_payload_section(
        endpoint="/metrics/history/context",
        scope=payload_scope,
        section="history",
        rows=len(history_items),
        total_rows=history_total,
        sampled=history_total > len(history_items),
    )
    record_api_payload_section(
        endpoint="/metrics/history/context",
        scope=payload_scope,
        section="selected_device_history",
        rows=len(selected_device_history_items),
        total_rows=selected_device_history_total,
        sampled=selected_history_sampled,
    )
    record_api_payload_section(
        endpoint="/metrics/history/context",
        scope=payload_scope,
        section="latest_snapshot",
        rows=len(latest_snapshot_items),
        total_rows=latest_snapshot_total,
        sampled=latest_snapshot_sampled,
    )
    record_api_payload_section(
        endpoint="/metrics/history/context",
        scope=payload_scope,
        section="selected_device_snapshot",
        rows=len(selected_device_snapshot_items),
        total_rows=selected_device_snapshot_total,
        sampled=selected_snapshot_sampled,
    )
    return {
        "metric_names": await repository.list_metric_names(device_id=device_id),
        "history": {
            "items": history_items,
            "meta": {"total": history_total, "limit": limit, "offset": 0},
        },
        "selected_device_history": {
            "items": selected_device_history_items,
            "meta": {
                "total": selected_device_history_total,
                "limit": selected_device_limit,
                "offset": selected_device_offset,
            },
        },
        "latest_snapshot": {
            "items": latest_snapshot_items,
            "meta": {"total": latest_snapshot_total, "limit": snapshot_limit, "offset": snapshot_offset},
        },
        "selected_device_snapshot": {
            "items": selected_device_snapshot_items,
            "meta": {"total": selected_device_snapshot_total, "limit": 500, "offset": 0},
        },
        "latest_snapshot_status_summary": latest_snapshot_status_summary,
        "snapshot_uptime_map": await repository.latest_snapshot_uptime_map_for_rows(latest_snapshot_rows),
    }


@router.get("/history/live")
async def get_metrics_history_live(
    limit: int = Query(default=100, ge=1, le=500),
    device_id: int | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    checked_from: datetime | None = Query(default=None),
    checked_to: datetime | None = Query(default=None),
    selected_device_limit: int = Query(default=200, ge=1, le=500),
    snapshot_limit: int = Query(default=10, ge=1, le=500),
    snapshot_offset: int = Query(default=0, ge=0),
    include_selected_device_snapshot: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repository = MetricRepository(db)
    # Live mode is intentionally fixed to the most recent 24 hours.
    live_checked_to = now()
    live_checked_from = live_checked_to - timedelta(hours=24)
    history_rows = await repository.list_recent_metric_rows(
        limit=limit,
        offset=0,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=live_checked_from,
        checked_to=live_checked_to,
    )
    selected_device_history_rows = []
    if device_id is not None:
        if selected_device_limit <= limit:
            selected_device_history_rows = history_rows[:selected_device_limit]
        else:
            selected_device_history_rows = await repository.list_recent_metric_rows(
                limit=selected_device_limit,
                offset=0,
                device_id=device_id,
                metric_name=metric_name,
                status=status,
                checked_from=live_checked_from,
                checked_to=live_checked_to,
            )

    latest_snapshot_rows, latest_snapshot_total = await repository.list_latest_metric_rows_paged(
        limit=snapshot_limit,
        offset=snapshot_offset,
        device_id=device_id,
    )
    if device_id is None:
        # Keep summary representative for all devices even when snapshot items are paged.
        latest_snapshot_status_summary = await repository.summarize_latest_snapshot_status_counts()
    else:
        latest_snapshot_status_summary = repository.summarize_latest_snapshot_status_counts_for_rows(latest_snapshot_rows)
    selected_device_snapshot_rows = []
    if include_selected_device_snapshot and device_id is not None:
        selected_device_snapshot_rows = await repository.list_latest_metric_rows(
            limit=500,
            offset=0,
            device_id=device_id,
        )

    history_items = _metric_history_dicts(history_rows)
    selected_device_history_items = _metric_history_dicts(selected_device_history_rows)
    snapshot_items = _metric_history_dicts(latest_snapshot_rows)
    selected_device_snapshot_items = _metric_history_dicts(selected_device_snapshot_rows)
    payload_scope = "device" if device_id is not None else "global"
    latest_snapshot_sampled = latest_snapshot_total > len(snapshot_items)
    record_api_payload_request(endpoint="/metrics/history/live", scope=payload_scope)
    record_api_payload_section(
        endpoint="/metrics/history/live",
        scope=payload_scope,
        section="history",
        rows=len(history_items),
        total_rows=len(history_items),
        sampled=True,
    )
    record_api_payload_section(
        endpoint="/metrics/history/live",
        scope=payload_scope,
        section="selected_device_history",
        rows=len(selected_device_history_items),
        total_rows=len(selected_device_history_items),
        sampled=True,
    )
    record_api_payload_section(
        endpoint="/metrics/history/live",
        scope=payload_scope,
        section="latest_snapshot",
        rows=len(snapshot_items),
        total_rows=latest_snapshot_total,
        sampled=latest_snapshot_sampled,
    )
    record_api_payload_section(
        endpoint="/metrics/history/live",
        scope=payload_scope,
        section="selected_device_snapshot",
        rows=len(selected_device_snapshot_items),
        total_rows=len(selected_device_snapshot_items),
        sampled=True,
    )
    return {
        "metric_names": await repository.list_metric_names(device_id=device_id),
        "history": {
            "items": history_items,
            "meta": {"total": len(history_items), "limit": limit, "offset": 0, "sampled": True},
        },
        "selected_device_history": {
            "items": selected_device_history_items,
            "meta": {
                "total": len(selected_device_history_items),
                "limit": selected_device_limit,
                "offset": 0,
                "sampled": True,
            },
        },
        "latest_snapshot": {
            "items": snapshot_items,
            "meta": {
                "total": latest_snapshot_total,
                "limit": snapshot_limit,
                "offset": snapshot_offset,
                "sampled": latest_snapshot_sampled,
            },
        },
        "selected_device_snapshot": {
            "items": selected_device_snapshot_items,
            "meta": {"total": len(selected_device_snapshot_items), "limit": 500, "offset": 0, "sampled": True},
        },
        "latest_snapshot_status_summary": latest_snapshot_status_summary,
        "snapshot_uptime_map": await repository.latest_snapshot_uptime_map_for_rows(latest_snapshot_rows),
    }


@router.get("/daily-summary", response_model=MetricDailySummaryPage)
async def get_metrics_daily_summary(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    device_id: int | None = Query(default=None),
    rollup_from: date | None = Query(default=None),
    rollup_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MetricDailySummaryPage:
    rows, total = await MetricRepository(db).list_daily_summary_rows_paged(
        limit=limit,
        offset=offset,
        device_id=device_id,
        rollup_from=rollup_from,
        rollup_to=rollup_to,
    )
    return MetricDailySummaryPage(
        items=[MetricDailySummaryItem(**row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/latest-snapshot/paged", response_model=MetricHistoryPage)
async def get_latest_metrics_snapshot_paged(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    device_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MetricHistoryPage:
    repository = MetricRepository(db)
    metrics, total = await repository.list_latest_metric_rows_paged(limit=limit, offset=offset, device_id=device_id)
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
