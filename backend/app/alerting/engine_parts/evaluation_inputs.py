"""Evaluation inputs: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import datetime

from ...core.time import utcnow
from ...models.alert import Alert
from ...models.device import Device
from ...models.metric import Metric
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.metric_repository import MetricRepository
from ...repositories.threshold_repository import ThresholdRepository
from ...services.threshold_service import threshold_for_device
from ..rules import ALERT_RULES
from .constants import ALERT_DYNAMIC_METRIC_NAME_PATTERNS, ALERT_EXACT_METRIC_NAMES
from .evaluation_context import AlertEvaluationContext
from .notification_policy import _alert_metric_stale_after_seconds as _alert_metric_stale_after_seconds
from .notification_policy import _metric_is_stale as _metric_is_stale
from .rule_evaluators import evaluate_expected_alerts_for_device


async def _load_alert_evaluation_inputs(
    *,
    metric_repository: MetricRepository,
    alert_repository: AlertRepository,
    device_repository: DeviceRepository,
    current_time: datetime | None = None,
) -> tuple[dict[tuple[int, str], Metric], list[Alert], list[Device], dict[int, Device], dict[int, str]]:
    """Load bounded metric/device/alert snapshots required for one evaluation cycle."""
    latest_metrics = await metric_repository.latest_metric_map_for_alert_evaluation(
        exact_metric_names=ALERT_EXACT_METRIC_NAMES,
        dynamic_metric_name_patterns=ALERT_DYNAMIC_METRIC_NAME_PATTERNS,
    )
    latest_metrics = _drop_stale_dynamic_alert_metrics(latest_metrics, current_time=current_time)
    active_alerts_list = await alert_repository.list_active_alerts_by_types(set(ALERT_RULES))
    active_alert_device_ids = {alert.device_id for alert in active_alerts_list if alert.device_id is not None}
    latest_metric_device_ids = {device_id for device_id, _metric_name in latest_metrics}
    candidate_device_ids = latest_metric_device_ids | active_alert_device_ids
    devices = await device_repository.list_devices_by_ids(candidate_device_ids, active_only=True)
    device_by_id = {device.id: device for device in devices}
    device_type_by_id = {device.id: device.device_type for device in devices}
    return latest_metrics, active_alerts_list, devices, device_by_id, device_type_by_id


def _drop_stale_dynamic_alert_metrics(
    latest_metrics: dict[tuple[int, str], Metric], *, current_time: datetime | None = None
) -> dict[tuple[int, str], Metric]:
    """Remove stale dynamic metric snapshots so renamed/removed objects do not keep alerts active."""
    if not latest_metrics:
        return latest_metrics

    current_time = current_time if current_time is not None else utcnow()
    stale_after_seconds = _alert_metric_stale_after_seconds()
    filtered_metrics = {}
    for key, metric in latest_metrics.items():
        _device_id, metric_name = key
        if _is_dynamic_alert_metric_name(metric_name) and _metric_is_stale(
            metric,
            current_time=current_time,
            stale_after_seconds=stale_after_seconds,
        ):
            continue
        filtered_metrics[key] = metric
    return filtered_metrics


def _is_dynamic_alert_metric_name(metric_name: str) -> bool:
    """Return whether a metric name belongs to an alert dynamic-object pattern."""
    metric_name = str(metric_name or "")
    for pattern in ALERT_DYNAMIC_METRIC_NAME_PATTERNS:
        prefix, suffix = pattern.split("%", 1)
        if metric_name.startswith(prefix) and metric_name.endswith(suffix):
            return True
    return False


async def _expected_alert_map(
    *,
    metric_repository: MetricRepository,
    devices: list,
    latest_metrics: dict,
    thresholds: dict,
    threshold_overrides: list[dict],
    active_maintenance_windows: list,
    active_alerts: list[Alert],
) -> dict[tuple[int | None, str], dict]:
    """Evaluate all device rules and return expected active alerts."""
    printer_device_ids = [device.id for device in devices if device.device_type == "printer"]
    printer_uptime_history_by_device = (
        await metric_repository.list_recent_metrics_by_device(
            device_ids=printer_device_ids,
            metric_name="printer_uptime_seconds",
            per_device_limit=2,
        )
        if printer_device_ids
        else {}
    )
    internet_target_device_ids = [device.id for device in devices if device.device_type == "internet_target"]
    internet_service_history_by_device = await _load_internet_service_history_by_device(
        metric_repository,
        internet_target_device_ids,
    )
    metric_history_by_device = await _load_rolling_metric_history_by_device(
        metric_repository,
        [device.id for device in devices],
        latest_metrics=latest_metrics,
    )

    expected_alerts: dict[tuple[int | None, str], dict] = {}
    for device in devices:
        if _device_in_maintenance(device, active_maintenance_windows):
            continue
        device_thresholds = _effective_thresholds_for_device(thresholds, threshold_overrides, device)
        evaluate_expected_alerts_for_device(
            AlertEvaluationContext(
                device=device,
                latest_metrics=latest_metrics,
                thresholds=device_thresholds,
                threshold_overrides=threshold_overrides,
                expected_alerts=expected_alerts,
                printer_uptime_history_by_device=printer_uptime_history_by_device,
                internet_service_history_by_device=internet_service_history_by_device,
                metric_history_by_device=metric_history_by_device,
            )
        )
    # Require three successful ping samples before resolving a reachability alert.
    # This prevents a one-cycle recovery from reopening Telegram noise during flaps.
    for alert in active_alerts:
        key = (alert.device_id, alert.alert_type)
        if alert.alert_type not in {"device_down", "internet_loss"} or key in expected_alerts:
            continue
        history = (
            metric_history_by_device.get(alert.device_id, {}).get("ping", []) if alert.device_id is not None else []
        )
        if len(history) < 3 or any(str(metric.status or "").lower() == "down" for metric in history[:3]):
            expected_alerts[key] = {
                "device_id": alert.device_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
            }
    return expected_alerts


async def _load_internet_service_history_by_device(
    metric_repository: MetricRepository,
    device_ids: list[int],
) -> dict[int, dict[str, list[Metric]]]:
    """Load bounded DNS/HTTP history used to debounce transient internet-service spikes."""
    if not device_ids:
        return {}
    return await metric_repository.list_recent_metrics_by_pairs(
        pairs=[(device_id, name) for device_id in device_ids for name in ("dns_resolution_time", "http_response_time")],
        per_pair_limit=2,
    )


async def _load_rolling_metric_history_by_device(
    metric_repository: MetricRepository,
    device_ids: list[int],
    *,
    latest_metrics: dict[tuple[int, str], Metric],
) -> dict[int, dict[str, list[Metric]]]:
    """Load recent metric windows used by rolling alert rules."""
    if not device_ids:
        return {}
    candidate_ids = set(device_ids)
    # Recovery of an existing reachability alert still needs ping history when
    # its latest snapshot is missing. Dynamic objects only need their own pair.
    pairs = {
        (device_id, metric_name) for device_id in candidate_ids for metric_name in ("ping", "packet_loss", "jitter")
    }
    pairs.update(
        (device_id, metric_name)
        for device_id, metric_name in latest_metrics
        if device_id in candidate_ids and metric_name.startswith("interface:") and metric_name.endswith("_mbps")
    )
    return await metric_repository.list_recent_metrics_by_pairs(pairs=sorted(pairs), per_pair_limit=5)


async def _load_active_maintenance_windows(db, devices: list) -> list:
    """Load active maintenance windows that match candidate device/site scopes."""
    device_ids = {device.id for device in devices if device.id is not None}
    sites = {str(device.site).strip() for device in devices if str(device.site or "").strip()}
    return await ThresholdRepository(db).active_maintenance_windows_for_devices(device_ids=device_ids, sites=sites)


def _device_in_maintenance(device, windows: list) -> bool:
    """Return whether a device is currently covered by a maintenance window."""
    for window in windows:
        if window.device_id is not None and window.device_id == device.id:
            return True
        if window.site and str(window.site).strip().lower() == str(device.site or "").strip().lower():
            return True
    return False


def _effective_thresholds_for_device(thresholds: dict[str, float], overrides: list[dict], device) -> dict[str, float]:
    """Return threshold map with scoped overrides applied for one device."""
    effective = dict(thresholds)
    for key in list(thresholds):
        effective[key] = threshold_for_device(thresholds, overrides, device, key)
    return effective
