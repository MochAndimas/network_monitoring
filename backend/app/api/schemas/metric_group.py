"""Bounded group monitoring response and explicit sampling/freshness metadata."""

from datetime import datetime

from pydantic import BaseModel

from .dashboard import MetricHistoryContextPayload


class GroupDeviceHealth(BaseModel):
    id: int
    name: str
    site: str | None
    device_type: str
    latest_checked_at: datetime | None
    status: str
    freshness: str


class MetricGroupMeta(BaseModel):
    total_devices: int
    device_limit: int
    device_offset: int
    has_more_devices: bool
    devices: list[GroupDeviceHealth]
    generated_at: datetime
    checked_from: datetime
    checked_to: datetime
    series_metric_names: list[str]
    metric_names_truncated: bool
    samples_per_series: int
    max_trend_items: int
    max_payload_bytes: int
    value_char_limit: int
    trend_sampled: bool


class MetricGroupPayload(MetricHistoryContextPayload):
    group: MetricGroupMeta
