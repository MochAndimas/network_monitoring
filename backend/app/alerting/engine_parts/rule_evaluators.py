"""Domain-specific alert-rule evaluators.

Each evaluator receives a per-device context and appends expected alert payloads.
The orchestration layer owns database reads/writes; this module owns rule shape.
"""

from __future__ import annotations

from collections.abc import Callable

from shared.device_utils import is_mikrotik_device
from shared.number_utils import safe_float

from .device_evaluators import _evaluate_mikrotik_alerts, _evaluate_nas_alerts
from .evaluation_context import AlertEvaluationContext
from .utils import _build_alert_payload, _metric_numeric_value, _threshold_for_device

RuleEvaluator = Callable[[AlertEvaluationContext], None]


def evaluate_expected_alerts_for_device(context: AlertEvaluationContext) -> None:
    """Run the registered alert evaluators for one device."""
    for evaluator in ALERT_RULE_EVALUATORS:
        evaluator(context)


def evaluate_reachability_alerts(context: AlertEvaluationContext) -> None:
    """Evaluate ping reachability and latency alerts."""
    device = context.device
    ping_metric = context.latest_metrics.get((device.id, "ping"))
    if ping_metric is not None and ping_metric.status == "down":
        alert_type = "internet_loss" if device.device_type == "internet_target" else "device_down"
        context.expected_alerts[(device.id, alert_type)] = _build_alert_payload(
            device_id=device.id,
            alert_type=alert_type,
            message=f"{device.name} is unreachable",
        )
        return

    if ping_metric is None:
        return

    ping_value = _metric_numeric_value(ping_metric)
    if ping_value is None:
        return

    warning_threshold = _threshold_for_device(context.thresholds, device.device_type, "ping_latency_warning")
    critical_threshold = _threshold_for_device(context.thresholds, device.device_type, "ping_latency_critical")
    if ping_value >= critical_threshold:
        context.expected_alerts[(device.id, "high_ping_latency_critical")] = _build_alert_payload(
            device_id=device.id,
            alert_type="high_ping_latency_critical",
            message=f"{device.name} ping latency reached {ping_value:.2f}{ping_metric.unit or ''}",
        )
    elif ping_value >= warning_threshold:
        context.expected_alerts[(device.id, "high_ping_latency_warning")] = _build_alert_payload(
            device_id=device.id,
            alert_type="high_ping_latency_warning",
            message=f"{device.name} ping latency reached {ping_value:.2f}{ping_metric.unit or ''}",
        )


def evaluate_quality_alerts(context: AlertEvaluationContext) -> None:
    """Evaluate packet loss and jitter alerts."""
    device = context.device
    for metric_name, warning_alert, critical_alert, warning_key, critical_key in QUALITY_METRIC_ALERTS:
        metric = context.latest_metrics.get((device.id, metric_name))
        if metric is None:
            continue
        value = safe_float(metric.metric_value)
        if value is None:
            continue
        warning_threshold = _threshold_for_device(context.thresholds, device.device_type, warning_key)
        critical_threshold = _threshold_for_device(context.thresholds, device.device_type, critical_key)
        if value >= critical_threshold:
            context.expected_alerts[(device.id, critical_alert)] = _build_alert_payload(
                device_id=device.id,
                alert_type=critical_alert,
                message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
            )
        elif value >= warning_threshold:
            context.expected_alerts[(device.id, warning_alert)] = _build_alert_payload(
                device_id=device.id,
                alert_type=warning_alert,
                message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
            )


def evaluate_internet_service_alerts(context: AlertEvaluationContext) -> None:
    """Evaluate DNS, HTTP, and public IP alerts."""
    device = context.device
    dns_metric = context.latest_metrics.get((device.id, "dns_resolution_time"))
    if dns_metric is not None:
        dns_value = safe_float(dns_metric.metric_value)
        if dns_metric.status == "down":
            context.expected_alerts[(device.id, "dns_resolution_failed")] = _build_alert_payload(
                device_id=device.id,
                alert_type="dns_resolution_failed",
                message=f"{device.name} DNS resolution failed",
            )
        elif _recent_internet_service_values_exceed_threshold(
            context,
            metric_name="dns_resolution_time",
            threshold=context.thresholds["dns_resolution_warning"],
        ):
            assert dns_value is not None
            context.expected_alerts[(device.id, "slow_dns_resolution")] = _build_alert_payload(
                device_id=device.id,
                alert_type="slow_dns_resolution",
                message=f"{device.name} DNS resolution reached {dns_value:.2f}{dns_metric.unit or ''}",
            )

    http_metric = context.latest_metrics.get((device.id, "http_response_time"))
    if http_metric is not None:
        http_value = safe_float(http_metric.metric_value)
        if http_metric.status == "down":
            context.expected_alerts[(device.id, "http_check_failed")] = _build_alert_payload(
                device_id=device.id,
                alert_type="http_check_failed",
                message=f"{device.name} HTTP check failed",
            )
        elif _recent_internet_service_values_exceed_threshold(
            context,
            metric_name="http_response_time",
            threshold=context.thresholds["http_response_warning"],
        ):
            assert http_value is not None
            context.expected_alerts[(device.id, "slow_http_response")] = _build_alert_payload(
                device_id=device.id,
                alert_type="slow_http_response",
                message=f"{device.name} HTTP response reached {http_value:.2f}{http_metric.unit or ''}",
            )

    public_ip_metric = context.latest_metrics.get((device.id, "public_ip"))
    if public_ip_metric is not None and public_ip_metric.status == "warning":
        context.expected_alerts[(device.id, "public_ip_changed")] = _build_alert_payload(
            device_id=device.id,
            alert_type="public_ip_changed",
            message=f"{device.name} public IP changed to {public_ip_metric.metric_value}",
        )


def _recent_internet_service_values_exceed_threshold(
    context: AlertEvaluationContext,
    *,
    metric_name: str,
    threshold: float,
    required_samples: int = 2,
) -> bool:
    """Return whether recent DNS/HTTP latency samples are consistently over threshold."""
    device_history = context.internet_service_history_by_device.get(context.device.id, {})
    recent_metrics = list(device_history.get(metric_name, []))[:required_samples]
    if len(recent_metrics) < required_samples:
        return False
    values = [safe_float(metric.metric_value) for metric in recent_metrics]
    return all(value is not None and value >= threshold for value in values)


def evaluate_resource_alerts(context: AlertEvaluationContext) -> None:
    """Evaluate host resource alerts such as CPU, RAM, and disk usage."""
    device = context.device
    for metric_name, alert_type, threshold_key in RESOURCE_METRIC_ALERTS:
        metric = context.latest_metrics.get((device.id, metric_name))
        if metric is None:
            continue
        value = _metric_numeric_value(metric)
        if value is None:
            continue
        if value >= context.thresholds[threshold_key]:
            context.expected_alerts[(device.id, alert_type)] = _build_alert_payload(
                device_id=device.id,
                alert_type=alert_type,
                message=f"{device.name} {metric_name} reached {value:.2f}{metric.unit or ''}",
            )


def evaluate_mikrotik_domain_alerts(context: AlertEvaluationContext) -> None:
    """Evaluate Mikrotik-specific alert rules when the device matches that domain."""
    device = context.device
    if not is_mikrotik_device(device.device_type, device.name):
        return
    _evaluate_mikrotik_alerts(
        device=device,
        latest_metrics=context.latest_metrics,
        thresholds=context.thresholds,
        expected_alerts=context.expected_alerts,
    )


def evaluate_nas_domain_alerts(context: AlertEvaluationContext) -> None:
    """Evaluate NAS-specific alert rules."""
    device = context.device
    if device.device_type != "nas":
        return
    _evaluate_nas_alerts(
        device=device,
        latest_metrics=context.latest_metrics,
        thresholds=context.thresholds,
        expected_alerts=context.expected_alerts,
    )


def evaluate_printer_domain_alerts(context: AlertEvaluationContext) -> None:
    """Evaluate printer-specific SNMP alert rules."""
    device = context.device
    if device.device_type != "printer":
        return

    uptime_metric = context.latest_metrics.get((device.id, "printer_uptime_seconds"))
    current_uptime = safe_float(uptime_metric.metric_value) if uptime_metric is not None else None
    if current_uptime is not None:
        uptime_history = context.printer_uptime_history_by_device.get(device.id, [])
        if len(uptime_history) >= 2:
            previous_uptime = safe_float(uptime_history[1].metric_value)
            if previous_uptime is not None and current_uptime < previous_uptime:
                context.expected_alerts[(device.id, "printer_reboot_detected")] = _build_alert_payload(
                    device_id=device.id,
                    alert_type="printer_reboot_detected",
                    message=f"{device.name} appears to have rebooted; uptime reset to {int(current_uptime)}s",
                )

    printer_status_metric = context.latest_metrics.get((device.id, "printer_status"))
    if printer_status_metric is not None and printer_status_metric.status == "warning":
        context.expected_alerts[(device.id, "printer_status_warning")] = _build_alert_payload(
            device_id=device.id,
            alert_type="printer_status_warning",
            message=f"{device.name} reported printer status {printer_status_metric.metric_value}",
        )

    printer_error_metric = context.latest_metrics.get((device.id, "printer_error_state"))
    if printer_error_metric is not None and printer_error_metric.metric_value not in {"", "none"}:
        context.expected_alerts[(device.id, "printer_error_state")] = _build_alert_payload(
            device_id=device.id,
            alert_type="printer_error_state",
            message=f"{device.name} printer error state: {printer_error_metric.metric_value.replace(',', ', ')}",
        )

    printer_paper_metric = context.latest_metrics.get((device.id, "printer_paper_status"))
    if printer_paper_metric is not None and printer_paper_metric.metric_value not in {"", "ok"}:
        context.expected_alerts[(device.id, "printer_paper_issue")] = _build_alert_payload(
            device_id=device.id,
            alert_type="printer_paper_issue",
            message=f"{device.name} paper status is {printer_paper_metric.metric_value}",
        )

    printer_ink_status_metric = context.latest_metrics.get((device.id, "printer_ink_status"))
    if printer_ink_status_metric is not None and printer_ink_status_metric.metric_value == "empty":
        context.expected_alerts[(device.id, "printer_ink_empty")] = _build_alert_payload(
            device_id=device.id,
            alert_type="printer_ink_empty",
            message=f"{device.name} ink status is empty",
        )
    elif printer_ink_status_metric is not None and printer_ink_status_metric.metric_value == "low":
        context.expected_alerts[(device.id, "printer_ink_low")] = _build_alert_payload(
            device_id=device.id,
            alert_type="printer_ink_low",
            message=f"{device.name} ink status is low",
        )


QUALITY_METRIC_ALERTS = (
    (
        "packet_loss",
        "high_packet_loss_warning",
        "high_packet_loss_critical",
        "packet_loss_warning",
        "packet_loss_critical",
    ),
    (
        "jitter",
        "high_jitter_warning",
        "high_jitter_critical",
        "jitter_warning",
        "jitter_critical",
    ),
)
RESOURCE_METRIC_ALERTS = (
    ("cpu_percent", "high_cpu", "cpu_warning"),
    ("memory_percent", "high_ram", "ram_warning"),
    ("disk_percent", "high_disk", "disk_warning"),
)
ALERT_RULE_EVALUATORS: tuple[RuleEvaluator, ...] = (
    evaluate_reachability_alerts,
    evaluate_quality_alerts,
    evaluate_internet_service_alerts,
    evaluate_resource_alerts,
    evaluate_mikrotik_domain_alerts,
    evaluate_nas_domain_alerts,
    evaluate_printer_domain_alerts,
)

__all__ = [
    "ALERT_RULE_EVALUATORS",
    "AlertEvaluationContext",
    "RuleEvaluator",
    "evaluate_expected_alerts_for_device",
]
