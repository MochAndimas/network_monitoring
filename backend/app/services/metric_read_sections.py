"""Metric read sections: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import datetime

from ..repositories.metric_repository import MetricRepository


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
