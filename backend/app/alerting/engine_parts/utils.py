"""Small pure helpers used by alert evaluation."""

from collections.abc import Mapping

from shared.number_utils import safe_float

from ...core.time import utcnow
from ...models.metric import Metric
from ..rules import ALERT_RULES


def metric_numeric_value(metric: Metric) -> float | None:
    """Return the numeric metric value using the precomputed column when available."""
    numeric_value = getattr(metric, "metric_value_numeric", None)
    if numeric_value is not None:
        try:
            return float(numeric_value)
        except (TypeError, ValueError):
            pass
    return safe_float(getattr(metric, "metric_value", None))


def threshold_for_device(thresholds: Mapping[str, float], device_type: str | None, key: str) -> float:
    """Return a device-specific threshold when configured, otherwise the global value."""
    device_key = f"{str(device_type or '').lower()}_{key}"
    return thresholds.get(device_key, thresholds[key])


def highest_dynamic_metric(
    latest_metrics: Mapping[tuple[int, str], Metric],
    *,
    device_id: int,
    prefix: str,
    suffixes: tuple[str, ...],
) -> tuple[str, Metric] | None:
    """Return the highest numeric dynamic metric matching a prefix and suffix set."""
    matches = [
        (metric_name, metric)
        for (current_device_id, metric_name), metric in latest_metrics.items()
        if current_device_id == device_id and str(metric_name).startswith(prefix) and str(metric_name).endswith(suffixes)
    ]
    numeric_matches = [
        (metric_name, metric, value)
        for metric_name, metric in matches
        if (value := safe_float(metric.metric_value)) is not None
    ]
    if not numeric_matches:
        return None
    metric_name, metric, _value = max(numeric_matches, key=lambda item: item[2])
    return metric_name, metric


def build_alert_payload(device_id: int | None, alert_type: str, message: str) -> dict:
    """Build the database payload for a newly active alert."""
    rule = ALERT_RULES[alert_type]
    return {
        "device_id": device_id,
        "alert_type": alert_type,
        "severity": rule["severity"],
        "message": message,
        "status": "active",
        "created_at": utcnow(),
    }


_metric_numeric_value = metric_numeric_value
_threshold_for_device = threshold_for_device
_highest_dynamic_metric = highest_dynamic_metric
_build_alert_payload = build_alert_payload

__all__ = [
    "_build_alert_payload",
    "_highest_dynamic_metric",
    "_metric_numeric_value",
    "_threshold_for_device",
    "build_alert_payload",
    "highest_dynamic_metric",
    "metric_numeric_value",
    "threshold_for_device",
]
