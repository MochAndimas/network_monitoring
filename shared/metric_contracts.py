"""Typed append-only payload crossing collector and metric repository boundaries."""

from datetime import datetime
from typing import NotRequired, TypedDict


class MetricWritePayload(TypedDict):
    device_id: int
    metric_name: str
    metric_value: str
    metric_value_numeric: NotRequired[float | None]
    status: NotRequired[str | None]
    unit: NotRequired[str | None]
    checked_at: NotRequired[datetime]
