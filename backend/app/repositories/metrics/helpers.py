"""Shared helpers for metric repository implementations."""

from datetime import datetime

from ...models.latest_metric import LatestMetric
from ...models.metric import Metric

UP_STATUSES = {"up", "ok"}


def is_metric_newer(metric: Metric, existing_checked_at: datetime | None, existing_metric_id: int | None) -> bool:
    """Return whether a metric sample is newer than the latest snapshot row."""
    if existing_checked_at is None:
        return True
    if metric.checked_at > existing_checked_at:
        return True
    if metric.checked_at < existing_checked_at:
        return False
    return int(metric.id) > int(existing_metric_id or 0)


def next_uptime_streak_started_at(
    *,
    existing: LatestMetric | None,
    latest_metric: Metric,
    ordered_metric_batch: list[Metric],
) -> datetime | None:
    """Return the start timestamp for the current consecutive up/ok streak."""
    status = str(latest_metric.status or "").lower()
    if status not in UP_STATUSES:
        return None
    last_non_up_index = -1
    for index, metric in enumerate(ordered_metric_batch):
        if str(metric.status or "").lower() not in UP_STATUSES:
            last_non_up_index = index
    if last_non_up_index >= 0:
        for metric in ordered_metric_batch[last_non_up_index + 1 :]:
            if str(metric.status or "").lower() in UP_STATUSES:
                return metric.checked_at
        return latest_metric.checked_at

    first_up_in_batch = next(
        (metric.checked_at for metric in ordered_metric_batch if str(metric.status or "").lower() in UP_STATUSES),
        latest_metric.checked_at,
    )
    if existing is None:
        return first_up_in_batch
    existing_status = str(existing.status or "").lower()
    if existing_status in UP_STATUSES and existing.uptime_streak_started_at is not None:
        return existing.uptime_streak_started_at
    return first_up_in_batch


def rollup_statuses(statuses: list[str]) -> str:
    """Collapse metric statuses into one device-level health label."""
    normalized = [str(status).lower() for status in statuses if status]
    if not normalized:
        return "unknown"
    if any(status in {"down", "critical", "error"} for status in normalized):
        return "down"
    if any(status in {"warning", "degraded", "unavailable"} for status in normalized):
        return "warning"
    if all(status in {"up", "healthy", "ok"} for status in normalized):
        return "up"
    return normalized[0]


_is_metric_newer = is_metric_newer
_next_uptime_streak_started_at = next_uptime_streak_started_at
_rollup_statuses = rollup_statuses

__all__ = [
    "UP_STATUSES",
    "_is_metric_newer",
    "_next_uptime_streak_started_at",
    "_rollup_statuses",
    "is_metric_newer",
    "next_uptime_streak_started_at",
    "rollup_statuses",
]
