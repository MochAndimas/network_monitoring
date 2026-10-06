"""Metric snapshot service: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.schemas import CursorPageMeta, MetricFreshnessItem, MetricFreshnessSummary, MetricHistoryPage
from ..core.time import now
from ..repositories.device_repository import DeviceRepository
from ..repositories.metric_repository import MetricRepository
from .metric_read_cursors import _decode_latest_snapshot_cursor, _latest_snapshot_next_cursor
from .metric_read_payloads import _freshness_status, _record_payload_section, metric_history_items
from .observability_service import record_api_payload_request, record_api_payload_section


async def get_latest_metrics_snapshot_page(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    cursor: str | None = None,
    device_id: int | None = None,
) -> MetricHistoryPage:
    """Return paginated latest-snapshot rows using keyset cursors."""
    repository = MetricRepository(db)
    if offset:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Offset pagination is not supported for latest snapshots; use cursor pagination",
        )
    if cursor:
        cursor_payload = _decode_latest_snapshot_cursor(cursor)
        metrics, has_more = await repository.list_latest_metric_rows_after_cursor(
            limit=limit,
            cursor_payload=cursor_payload,
            device_id=device_id,
        )
        total = None
        next_cursor = _latest_snapshot_next_cursor(metrics) if has_more else None
    else:
        metrics, total = await repository.list_latest_metric_rows_paged(limit=limit, offset=offset, device_id=device_id)
        has_more = total > len(metrics)
        next_cursor = _latest_snapshot_next_cursor(metrics) if has_more else None
    _record_payload_section(
        endpoint="/metrics/latest-snapshot/paged",
        device_id=device_id,
        section="items",
        rows=len(metrics),
        total_rows=total,
        sampled=has_more if total is None else total > len(metrics),
    )
    return MetricHistoryPage(
        items=metric_history_items(metrics),
        meta=CursorPageMeta(
            total=total,
            limit=limit,
            offset=0 if cursor else offset,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


async def get_latest_snapshot_status_summary(db: AsyncSession) -> dict[str, int]:
    """Return latest-snapshot status counts."""
    return await MetricRepository(db).summarize_latest_snapshot_status_counts()


async def get_latest_snapshot_uptime_map(db: AsyncSession, *, limit: int, offset: int) -> dict[str, str]:
    """Return latest-snapshot uptime durations keyed by device and metric."""
    if offset:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Offset pagination is not supported for latest snapshot uptime maps",
        )
    return await MetricRepository(db).latest_snapshot_uptime_map(limit=limit, offset=offset)


async def get_metric_freshness_summary(
    db: AsyncSession,
    *,
    stale_after_minutes: int,
    active_only: bool,
) -> MetricFreshnessSummary:
    """Return collector/site data freshness based on latest metric snapshots."""
    generated_at = now()
    stale_cutoff = generated_at - timedelta(minutes=stale_after_minutes)
    rows = await DeviceRepository(db).summarize_freshness_by_collector_site(
        stale_cutoff=stale_cutoff,
        active_only=active_only,
    )
    items = [
        MetricFreshnessItem(
            **row,
            freshness_status=_freshness_status(row),
        )
        for row in rows
    ]
    record_api_payload_request(endpoint="/metrics/freshness/summary", scope="active" if active_only else "all")
    record_api_payload_section(
        endpoint="/metrics/freshness/summary",
        scope="active" if active_only else "all",
        section="items",
        rows=len(items),
        total_rows=len(items),
        sampled=False,
    )
    return MetricFreshnessSummary(
        generated_at=generated_at,
        stale_after_minutes=stale_after_minutes,
        active_only=active_only,
        items=items,
    )
