"""Compatibility composition for metric repository operations."""

from .history import MetricHistoryMixin
from .latest import MetricLatestMixin
from .rollups import MetricRollupMixin
from .writes import MetricWriteMixin


class MetricRepository(
    MetricWriteMixin,
    MetricHistoryMixin,
    MetricLatestMixin,
    MetricRollupMixin,
):
    """Database access object for metric write, history, latest snapshot, and rollup records."""


__all__ = ["MetricRepository"]
