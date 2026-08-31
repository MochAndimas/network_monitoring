"""Read-model service for metric history, snapshots, and dashboard context payloads."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.pagination import decode_page_cursor, encode_page_cursor
from ..api.schemas import (
    CursorPageMeta,
    MetricDailySummaryItem,
    MetricDailySummaryPage,
    MetricColdArchiveItem,
    MetricColdArchivePage,
    MetricFreshnessItem,
    MetricFreshnessSummary,
    MetricHistoryContextPayload,
    MetricHistoryCursorPage,
    MetricHistoryItem,
    MetricHistoryPage,
    MetricLongTermExplorerPayload,
    MetricHistorySection,
    MetricSiteTypeTrendItem,
    MetricPayloadMeta,
    PageMeta,
)
from ..core.time import now
from ..repositories.device_repository import DeviceRepository
from ..repositories.metric_repository import MetricRepository
from .observability_service import record_api_payload_request, record_api_payload_section


def metric_history_dicts(metrics: list[dict]) -> list[dict]:
    """Convert repository metric rows into API response dictionaries."""
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


def metric_history_items(metrics: list[dict]) -> list[MetricHistoryItem]:
    """Convert repository metric rows into typed MetricHistoryItem objects."""
    return [MetricHistoryItem(**metric) for metric in metric_history_dicts(metrics)]


def _history_section(
    items: list[dict],
    *,
    total: int,
    limit: int,
    offset: int,
    sampled: bool | None = None,
) -> MetricHistorySection:
    """Build a typed composite metric payload section."""
    return MetricHistorySection(
        items=[MetricHistoryItem(**item) for item in items],
        meta=MetricPayloadMeta(total=total, limit=limit, offset=offset, sampled=sampled),
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
    if device_id is None:
        latest_snapshot_status_summary = await repository.summarize_latest_snapshot_status_counts()
    else:
        latest_snapshot_status_summary = repository.summarize_latest_snapshot_status_counts_for_rows(latest_snapshot_rows)
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
        snapshot_uptime_map=await repository.latest_snapshot_uptime_map_for_rows(latest_snapshot_rows),
    )


async def get_metrics_daily_summary(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    device_id: int | None = None,
    site: str | None = None,
    device_type: str | None = None,
    rollup_from: date | None = None,
    rollup_to: date | None = None,
) -> MetricDailySummaryPage:
    """Return paginated daily metric rollup rows."""
    rows, total = await MetricRepository(db).list_daily_summary_rows_paged(
        limit=limit,
        offset=offset,
        device_id=device_id,
        site=site,
        device_type=device_type,
        rollup_from=rollup_from,
        rollup_to=rollup_to,
    )
    _record_payload_section(
        endpoint="/metrics/daily-summary",
        device_id=device_id,
        section="items",
        rows=len(rows),
        total_rows=total,
        sampled=total > len(rows),
    )
    return MetricDailySummaryPage(
        items=[MetricDailySummaryItem(**row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


async def get_metrics_long_term_explorer(
    db: AsyncSession,
    *,
    archive_from: date | None,
    archive_to: date | None,
    metric_name: str | None,
    site: str | None,
    device_type: str | None,
    limit: int,
    offset: int,
) -> MetricLongTermExplorerPayload:
    """Return long-term trend and cold archive rows without scanning raw metrics."""
    repository = MetricRepository(db)
    trends = await repository.list_long_term_trend_rows(
        rollup_from=archive_from,
        rollup_to=archive_to,
        site=site,
        device_type=device_type,
        limit=366,
    )
    archive_rows, total = await repository.list_cold_archive_rows(
        archive_from=archive_from,
        archive_to=archive_to,
        metric_name=metric_name,
        site=site,
        device_type=device_type,
        limit=limit,
        offset=offset,
    )
    record_api_payload_request(endpoint="/metrics/long-term-explorer", scope="archive")
    record_api_payload_section(
        endpoint="/metrics/long-term-explorer",
        scope="archive",
        section="trends",
        rows=len(trends),
        total_rows=len(trends),
        sampled=False,
    )
    record_api_payload_section(
        endpoint="/metrics/long-term-explorer",
        scope="archive",
        section="archives",
        rows=len(archive_rows),
        total_rows=total,
        sampled=total > len(archive_rows),
    )
    return MetricLongTermExplorerPayload(
        trends=[MetricSiteTypeTrendItem(**row) for row in trends],
        archives=MetricColdArchivePage(
            items=[MetricColdArchiveItem(**row) for row in archive_rows],
            meta=PageMeta(total=total, limit=limit, offset=offset),
        ),
    )


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


def _freshness_status(row: dict) -> str:
    """Return rollup freshness status for one collector/site bucket."""
    total_devices = int(row.get("total_devices") or 0)
    no_data_devices = int(row.get("no_data_devices") or 0)
    stale_devices = int(row.get("stale_devices") or 0)
    fresh_devices = int(row.get("fresh_devices") or 0)
    if total_devices <= 0 or no_data_devices >= total_devices:
        return "no_data"
    if stale_devices or no_data_devices:
        return "stale"
    if fresh_devices >= total_devices:
        return "fresh"
    return "unknown"


async def _selected_device_history(
    repository: MetricRepository,
    *,
    history_rows: list[dict],
    history_total: int,
    device_id: int | None,
    metric_name: str | None,
    status: str | None,
    checked_from: datetime | None,
    checked_to: datetime | None,
    selected_device_limit: int,
    selected_device_offset: int,
    initial_limit: int,
) -> tuple[list[dict], int]:
    """Return selected-device history, reusing the global query when possible."""
    if device_id is None:
        return [], 0
    if selected_device_offset == 0 and selected_device_limit <= initial_limit:
        return history_rows[:selected_device_limit], history_total
    return await repository.list_recent_metric_rows_paged(
        limit=selected_device_limit,
        offset=selected_device_offset,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )


async def _selected_device_live_history(
    repository: MetricRepository,
    *,
    history_rows: list[dict],
    device_id: int | None,
    metric_name: str | None,
    status: str | None,
    checked_from: datetime,
    checked_to: datetime,
    selected_device_limit: int,
    initial_limit: int,
) -> list[dict]:
    """Return selected-device live history, reusing the primary sample when possible."""
    if device_id is None:
        return []
    if selected_device_limit <= initial_limit:
        return history_rows[:selected_device_limit]
    return await repository.list_recent_metric_rows(
        limit=selected_device_limit,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )


async def _selected_device_trend(
    repository: MetricRepository,
    *,
    device_id: int | None,
    metric_name: str | None,
    metric_names: list[str] | None,
    status: str | None,
    checked_from: datetime | None,
    checked_to: datetime | None,
    include_selected_device_trend: bool,
    trend_limit: int,
) -> tuple[list[dict], int]:
    """Return bounded selected-device trend rows for dashboard investigation mode."""
    if not include_selected_device_trend or device_id is None:
        return [], 0
    normalized_metric_names = _trend_metric_names(metric_name=metric_name, metric_names=metric_names)
    rows, total = await repository.list_recent_metric_rows_paged(
        limit=trend_limit,
        offset=0,
        device_id=device_id,
        metric_name=metric_name if not normalized_metric_names else None,
        metric_names=normalized_metric_names,
        per_metric_limit=trend_limit if normalized_metric_names else None,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )
    return rows, total


async def _selected_device_live_trend(
    repository: MetricRepository,
    *,
    device_id: int | None,
    metric_name: str | None,
    metric_names: list[str] | None,
    status: str | None,
    checked_from: datetime,
    checked_to: datetime,
    include_selected_device_trend: bool,
    trend_limit: int,
) -> list[dict]:
    """Return bounded selected-device trend rows for auto-refresh live mode."""
    if not include_selected_device_trend or device_id is None:
        return []
    normalized_metric_names = _trend_metric_names(metric_name=metric_name, metric_names=metric_names)
    if normalized_metric_names:
        rows, _total = await repository.list_recent_metric_rows_paged(
            limit=trend_limit,
            offset=0,
            device_id=device_id,
            metric_names=normalized_metric_names,
            per_metric_limit=trend_limit,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        return rows
    return await repository.list_recent_metric_rows(
        limit=trend_limit,
        device_id=device_id,
        metric_name=metric_name,
        status=status,
        checked_from=checked_from,
        checked_to=checked_to,
    )


def _trend_metric_names(*, metric_name: str | None, metric_names: list[str] | None) -> list[str]:
    """Return explicit trend metric names, preferring a selected single metric."""
    if metric_name:
        return [metric_name]
    if not metric_names:
        return []
    return list(dict.fromkeys(str(item) for item in metric_names if str(item or "").strip()))


async def _selected_device_snapshot(
    repository: MetricRepository,
    *,
    device_id: int | None,
    include_selected_device_snapshot: bool,
) -> tuple[list[dict], int]:
    """Return selected-device latest snapshots when explicitly requested."""
    if not include_selected_device_snapshot or device_id is None:
        return [], 0
    return await repository.list_latest_metric_rows_paged(limit=500, offset=0, device_id=device_id)


async def _snapshot_status_summary(
    repository: MetricRepository,
    *,
    latest_snapshot_rows: list[dict],
    latest_snapshot_total: int,
    snapshot_limit: int,
    snapshot_offset: int,
) -> dict[str, int]:
    """Return representative latest-snapshot status summary for context payloads."""
    if snapshot_offset == 0 and latest_snapshot_total <= snapshot_limit:
        return repository.summarize_latest_snapshot_status_counts_for_rows(latest_snapshot_rows)
    return await repository.summarize_latest_snapshot_status_counts()


def _record_payload_section(
    *,
    endpoint: str,
    device_id: int | None,
    section: str,
    rows: int,
    total_rows: int | None,
    sampled: bool,
) -> None:
    """Record observability counters for one metric API payload section."""
    payload_scope = "device" if device_id is not None else "global"
    record_api_payload_request(endpoint=endpoint, scope=payload_scope)
    record_api_payload_section(
        endpoint=endpoint,
        scope=payload_scope,
        section=section,
        rows=rows,
        total_rows=total_rows,
        sampled=sampled,
    )


def _record_context_payload_sections(
    *,
    endpoint: str,
    device_id: int | None,
    history_items: list[dict],
    history_total: int,
    selected_device_history_items: list[dict],
    selected_device_history_total: int,
    selected_device_trend_items: list[dict],
    selected_device_trend_total: int,
    latest_snapshot_items: list[dict],
    latest_snapshot_total: int,
    selected_device_snapshot_items: list[dict],
    selected_device_snapshot_total: int,
    force_sampled: bool = False,
    latest_snapshot_sampled: bool | None = None,
) -> None:
    """Record observability counters for composite metric context payloads."""
    payload_scope = "device" if device_id is not None else "global"
    record_api_payload_request(endpoint=endpoint, scope=payload_scope)
    sections = (
        ("history", history_items, history_total, force_sampled or history_total > len(history_items)),
        (
            "selected_device_history",
            selected_device_history_items,
            selected_device_history_total,
            force_sampled or selected_device_history_total > len(selected_device_history_items),
        ),
        (
            "selected_device_trend",
            selected_device_trend_items,
            selected_device_trend_total,
            force_sampled or selected_device_trend_total > len(selected_device_trend_items),
        ),
        (
            "latest_snapshot",
            latest_snapshot_items,
            latest_snapshot_total,
            latest_snapshot_sampled if latest_snapshot_sampled is not None else latest_snapshot_total > len(latest_snapshot_items),
        ),
        (
            "selected_device_snapshot",
            selected_device_snapshot_items,
            selected_device_snapshot_total,
            force_sampled or selected_device_snapshot_total > len(selected_device_snapshot_items),
        ),
    )
    for section, items, total_rows, sampled in sections:
        record_api_payload_section(
            endpoint=endpoint,
            scope=payload_scope,
            section=section,
            rows=len(items),
            total_rows=total_rows,
            sampled=sampled,
        )


def _metric_history_next_cursor(metrics: list[dict]) -> str | None:
    """Build a cursor from the last row in a metric-history page."""
    if not metrics:
        return None
    last_metric = metrics[-1]
    checked_at = last_metric["checked_at"]
    checked_at_value = checked_at.isoformat() if hasattr(checked_at, "isoformat") else str(checked_at)
    return encode_page_cursor({"checked_at": checked_at_value, "id": int(last_metric["id"])})


def _decode_metric_history_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode a metric-history keyset cursor from the public API token."""
    payload = decode_page_cursor(cursor, detail="Invalid metrics history cursor")
    try:
        checked_at = datetime.fromisoformat(str(payload["checked_at"]))
        metric_id = int(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid metrics history cursor") from exc
    return checked_at, metric_id


def _latest_snapshot_next_cursor(metrics: list[dict]) -> str | None:
    """Build a cursor from the last row in a latest-snapshot page."""
    if not metrics:
        return None
    last_metric = metrics[-1]
    return encode_page_cursor(
        {
            "device_type_priority": int(last_metric["_sort_device_type_priority"]),
            "internet_target_name_priority": int(last_metric["_sort_internet_target_name_priority"]),
            "device_name": str(last_metric["_sort_device_name"]),
            "metric_name": str(last_metric["_sort_metric_name"]),
            "id": int(last_metric["id"]),
        }
    )


def _decode_latest_snapshot_cursor(cursor: str) -> dict:
    """Decode the latest-snapshot cursor used by keyset pagination."""
    payload = decode_page_cursor(cursor, detail="Invalid latest snapshot cursor")
    try:
        return {
            "device_type_priority": int(payload["device_type_priority"]),
            "internet_target_name_priority": int(payload["internet_target_name_priority"]),
            "device_name": str(payload["device_name"]),
            "metric_name": str(payload["metric_name"]),
            "id": int(payload["id"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid latest snapshot cursor") from exc
