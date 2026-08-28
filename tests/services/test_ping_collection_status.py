"""Verify ICMP target health is not confused with local collector failures."""

from types import SimpleNamespace

from backend.app.alerting.engine_parts.evaluation_context import AlertEvaluationContext
from backend.app.alerting.engine_parts.rule_evaluators import evaluate_reachability_alerts
from backend.app.monitors.helpers import PingProbeResult, build_ping_check_metrics


def test_ping_timeout_is_target_down_when_collector_succeeds():
    metrics = build_ping_check_metrics(7, [PingProbeResult(None, "ok")])
    by_name = {metric["metric_name"]: metric for metric in metrics}

    assert by_name["ping_collection_status"]["metric_value"] == "ok"
    assert by_name["ping"]["status"] == "down"


def test_collector_error_does_not_create_device_down_alert():
    metrics = build_ping_check_metrics(7, [PingProbeResult(None, "connection_failed")])
    by_name = {metric["metric_name"]: SimpleNamespace(**metric) for metric in metrics}
    context = AlertEvaluationContext(
        device=SimpleNamespace(id=7, name="Router Test", device_type="switch"),
        latest_metrics={(7, name): metric for name, metric in by_name.items()},
        thresholds={},
        threshold_overrides=[],
        expected_alerts={},
        printer_uptime_history_by_device={},
        internet_service_history_by_device={},
        metric_history_by_device={},
    )

    evaluate_reachability_alerts(context)

    assert (7, "ping_collection_degraded") in context.expected_alerts
    assert (7, "device_down") not in context.expected_alerts
