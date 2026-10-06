"""Metric history service: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.schemas import CursorPageMeta, MetricHistoryContextPayload, MetricHistoryCursorPage, MetricHistoryItem
from ..core.time import now
from ..repositories.metric_repository import MetricRepository
from .metric_read_cursors import _decode_metric_history_cursor, _metric_history_next_cursor
from .metric_read_payloads import (
    _device_monitoring_context,
    _history_section,
    _record_context_payload_sections,
    _record_payload_section,
    metric_history_dicts,
    metric_history_items,
)
from .metric_read_sections import (
    _selected_device_history,
    _selected_device_live_history,
    _selected_device_live_trend,
    _selected_device_snapshot,
    _selected_device_trend,
    _snapshot_status_summary,
)


async def list_metric_names(db: AsyncSession, *, device_id: int | None = None) -> list[str]:
    """Return metric names present in the latest snapshot."""
    return await MetricRepository(db).list_metric_names(device_id=device_id)


async def get_metrics_history(
    db: AsyncSession,
    *,
    limit: int,
    device_id: int | None = None,
    site: str | None = None,
    device_type: str | None = None,
    metric_name: str | None = None,
    status: str | None = None,
    checked_from: datetime | None = None,
    checked_to: datetime | None = None,
) -> list[MetricHistoryItem]:
    """Return legacy metric history rows."""
    metrics = await MetricRepository(db).list_recent_metric_rows(
        limit=limit,
        device_id=device_id,
        site=site,
        device_type=device_type,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )
    return metric_history_items(metrics)


async def get_metrics_history_page(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    cursor: str | None = None,
    device_id: int | None = None,
    metric_name: str | None = None,
    metric_names: list[str] | None = None,
    per_metric_limit: int | None = None,
    status: str | None = None,
    checked_from: datetime | None = None,
    checked_to: datetime | None = None,
) -> MetricHistoryCursorPage:
    """Return paginated metric history using keyset cursors."""
    repository = MetricRepository(db)
    if offset:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Offset pagination is not supported for metric history; use cursor pagination",
        )
    if cursor:
        if per_metric_limit is not None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cursor pagination is not supported with per_metric_limit",
            )
        cursor_checked_at, cursor_id = _decode_metric_history_cursor(cursor)
        metrics, has_more = await repository.list_recent_metric_rows_after_cursor(
            limit=limit,
            cursor_checked_at=cursor_checked_at,
            cursor_id=cursor_id,
            device_id=device_id,
            metric_name=metric_name,
            metric_names=metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        total = None
        next_cursor = _metric_history_next_cursor(metrics) if has_more else None
    else:
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
        has_more = total > len(metrics)
        next_cursor = _metric_history_next_cursor(metrics) if has_more and per_metric_limit is None else None

    _record_payload_section(
        endpoint="/metrics/history/paged",
        device_id=device_id,
        section="items",
        rows=len(metrics),
        total_rows=total,
        sampled=has_more if total is None else total > len(metrics),
    )
    return MetricHistoryCursorPage(
        items=metric_history_items(metrics),
        meta=CursorPageMeta(
            total=total,
            limit=limit,
            offset=0 if cursor else offset,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


async def get_metrics_history_context(
    db: AsyncSession,
    *,
    limit: int,
    device_id: int | None = None,
    metric_name: str | None = None,
    status: str | None = None,
    checked_from: datetime | None = None,
    checked_to: datetime | None = None,
    selected_device_limit: int,
    selected_device_offset: int,
    include_selected_device_trend: bool,
    trend_metric_names: list[str] | None,
    trend_limit: int,
    snapshot_limit: int,
    snapshot_offset: int,
    include_selected_device_snapshot: bool,
) -> MetricHistoryContextPayload:
    """Return the dashboard history context payload."""
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
    selected_device_history_rows, selected_device_history_total = await _selected_device_history(
        repository,
        history_rows=history_rows,
        history_total=history_total,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
        selected_device_limit=selected_device_limit,
        selected_device_offset=selected_device_offset,
        initial_limit=limit,
    )
    selected_device_trend_rows, selected_device_trend_total = await _selected_device_trend(
        repository,
        device_id=device_id,
        metric_name=metric_name,
        metric_names=trend_metric_names,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
        include_selected_device_trend=include_selected_device_trend,
        trend_limit=trend_limit,
    )
    latest_snapshot_rows, latest_snapshot_total = await repository.list_latest_metric_rows_paged(
        limit=snapshot_limit,
        offset=snapshot_offset,
    )
    latest_snapshot_status_summary = await _snapshot_status_summary(
        repository,
        latest_snapshot_rows=latest_snapshot_rows,
        latest_snapshot_total=latest_snapshot_total,
        snapshot_limit=snapshot_limit,
        snapshot_offset=snapshot_offset,
    )
    selected_device_snapshot_rows, selected_device_snapshot_total = await _selected_device_snapshot(
        repository,
        device_id=device_id,
        include_selected_device_snapshot=include_selected_device_snapshot,
    )

    history_items = metric_history_dicts(history_rows)
    selected_device_history_items = (
        history_items
        if selected_device_history_rows is history_rows
        else metric_history_dicts(selected_device_history_rows)
    )
    selected_device_trend_items = metric_history_dicts(selected_device_trend_rows)
    latest_snapshot_items = metric_history_dicts(latest_snapshot_rows)
    selected_device_snapshot_items = metric_history_dicts(selected_device_snapshot_rows)
    device_context = _device_monitoring_context(selected_device_snapshot_items) if device_id is not None else None
    _record_context_payload_sections(
        endpoint="/metrics/history/context",
        device_id=device_id,
        history_items=history_items,
        history_total=history_total,
        selected_device_history_items=selected_device_history_items,
        selected_device_history_total=selected_device_history_total,
        selected_device_trend_items=selected_device_trend_items,
        selected_device_trend_total=selected_device_trend_total,
        latest_snapshot_items=latest_snapshot_items,
        latest_snapshot_total=latest_snapshot_total,
        selected_device_snapshot_items=selected_device_snapshot_items,
        selected_device_snapshot_total=selected_device_snapshot_total,
    )
    return MetricHistoryContextPayload(
        metric_names=await repository.list_metric_names(device_id=device_id),
        history=_history_section(history_items, total=history_total, limit=limit, offset=0),
        selected_device_history=_history_section(
            selected_device_history_items,
            total=selected_device_history_total,
            limit=selected_device_limit,
            offset=selected_device_offset,
        ),
        selected_device_trend=_history_section(
            selected_device_trend_items,
            total=selected_device_trend_total,
            limit=trend_limit,
            offset=0,
            sampled=selected_device_trend_total > len(selected_device_trend_items),
        ),
        latest_snapshot=_history_section(
            latest_snapshot_items,
            total=latest_snapshot_total,
            limit=snapshot_limit,
            offset=snapshot_offset,
        ),
        selected_device_snapshot=_history_section(
            selected_device_snapshot_items,
            total=selected_device_snapshot_total,
            limit=500,
            offset=0,
        ),
        latest_snapshot_status_summary=latest_snapshot_status_summary,
        device_context=device_context,
        snapshot_uptime_map=await repository.latest_snapshot_uptime_map_for_rows(latest_snapshot_rows),
    )


async def get_metrics_history_live(
    db: AsyncSession,
    *,
    limit: int,
    device_id: int | None = None,
    metric_name: str | None = None,
    status: str | None = None,
    selected_device_limit: int,
    include_selected_device_trend: bool,
    trend_metric_names: list[str] | None,
    trend_limit: int,
    snapshot_limit: int,
    snapshot_offset: int,
    include_selected_device_snapshot: bool,
) -> MetricHistoryContextPayload:
    """Return the live dashboard history payload using the latest 24-hour window."""
    repository = MetricRepository(db)
    live_checked_to = now()
    live_checked_from = live_checked_to - timedelta(hours=24)
    history_rows = await repository.list_recent_metric_rows(
        limit=limit,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=live_checked_from,
        checked_to=live_checked_to,
    )
    selected_device_history_rows = await _selected_device_live_history(
        repository,
        history_rows=history_rows,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=live_checked_from,
        checked_to=live_checked_to,
        selected_device_limit=selected_device_limit,
        initial_limit=limit,
    )
    selected_device_trend_rows = await _selected_device_live_trend(
        repository,
        device_id=device_id,
        metric_name=metric_name,
        metric_names=trend_metric_names,
        status=status,
        checked_from=live_checked_from,
        checked_to=live_checked_to,
        include_selected_device_trend=include_selected_device_trend,
        trend_limit=trend_limit,
    )
    latest_snapshot_rows, latest_snapshot_total = await repository.list_latest_metric_rows_paged(
        limit=snapshot_limit,
        offset=snapshot_offset,
        device_id=device_id,
    )
    latest_snapshot_status_summary = await repository.summarize_latest_snapshot_status_counts(device_id=device_id)
    selected_device_snapshot_rows = []
    if include_selected_device_snapshot and device_id is not None:
        selected_device_snapshot_rows = await repository.list_latest_metric_rows(
            limit=500,
            device_id=device_id,
        )

    history_items = metric_history_dicts(history_rows)
    selected_device_history_items = metric_history_dicts(selected_device_history_rows)
    selected_device_trend_items = metric_history_dicts(selected_device_trend_rows)
    snapshot_items = metric_history_dicts(latest_snapshot_rows)
    selected_device_snapshot_items = metric_history_dicts(selected_device_snapshot_rows)
    latest_snapshot_sampled = latest_snapshot_total > len(snapshot_items)
    _record_context_payload_sections(
        endpoint="/metrics/history/live",
        device_id=device_id,
        history_items=history_items,
        history_total=len(history_items),
        selected_device_history_items=selected_device_history_items,
        selected_device_history_total=len(selected_device_history_items),
        selected_device_trend_items=selected_device_trend_items,
        selected_device_trend_total=len(selected_device_trend_items),
        latest_snapshot_items=snapshot_items,
        latest_snapshot_total=latest_snapshot_total,
        selected_device_snapshot_items=selected_device_snapshot_items,
        selected_device_snapshot_total=len(selected_device_snapshot_items),
        force_sampled=True,
        latest_snapshot_sampled=latest_snapshot_sampled,
    )
    return MetricHistoryContextPayload(
        metric_names=await repository.list_metric_names(device_id=device_id),
        history=_history_section(history_items, total=len(history_items), limit=limit, offset=0, sampled=True),
        selected_device_history=_history_section(
            selected_device_history_items,
            total=len(selected_device_history_items),
            limit=selected_device_limit,
            offset=0,
            sampled=True,
        ),
        selected_device_trend=_history_section(
            selected_device_trend_items,
            total=len(selected_device_trend_items),
            limit=trend_limit,
            offset=0,
            sampled=True,
        ),
        latest_snapshot=_history_section(
            snapshot_items,
            total=latest_snapshot_total,
            limit=snapshot_limit,
            offset=snapshot_offset,
            sampled=latest_snapshot_sampled,
        ),
        selected_device_snapshot=_history_section(
            selected_device_snapshot_items,
            total=len(selected_device_snapshot_items),
            limit=500,
            offset=0,
            sampled=True,
        ),
        latest_snapshot_status_summary=latest_snapshot_status_summary,
        device_context=_device_monitoring_context(selected_device_snapshot_items) if device_id is not None else None,
        snapshot_uptime_map=await repository.latest_snapshot_uptime_map_for_rows(latest_snapshot_rows),
    )
