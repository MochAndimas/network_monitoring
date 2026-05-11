"""Metric write and latest-snapshot upsert entry points."""

from .impl import MetricRepository, _is_metric_newer, _next_uptime_streak_started_at

__all__ = ["MetricRepository", "_is_metric_newer", "_next_uptime_streak_started_at"]

