"""Shared context object passed to domain-specific alert evaluators."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from ...models.device import Device
from ...models.metric import Metric

MetricHistoryByName = Mapping[str, list[Metric]]


@dataclass(slots=True)
class AlertEvaluationContext:
    """Input and output state for one device's alert-rule evaluation."""

    device: Device
    latest_metrics: Mapping[tuple[int, str], Metric]
    thresholds: dict[str, float]
    threshold_overrides: list[dict]
    expected_alerts: dict[tuple[int | None, str], dict]
    printer_uptime_history_by_device: Mapping[int, list[Metric]]
    internet_service_history_by_device: Mapping[int, MetricHistoryByName]
    metric_history_by_device: Mapping[int, MetricHistoryByName]


__all__ = ["AlertEvaluationContext", "MetricHistoryByName"]
