"""Compatibility facade for metric persistence and query helpers.

The implementation is split under ``backend.app.repositories.metrics``.
This module keeps the historical import path stable for services, routes, and tests.
"""

from .metrics.helpers import UP_STATUSES, _is_metric_newer, _next_uptime_streak_started_at, _rollup_statuses
from .metrics.impl import MetricRepository

__all__ = [
    "MetricRepository",
    "UP_STATUSES",
    "_is_metric_newer",
    "_next_uptime_streak_started_at",
    "_rollup_statuses",
]
