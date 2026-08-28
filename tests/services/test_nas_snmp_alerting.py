"""Unit tests for NAS SNMP collector-health alert behavior."""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.alerting.engine_parts.evaluation_context import AlertEvaluationContext
from backend.app.alerting.engine_parts.rule_evaluators import evaluate_nas_domain_alerts


def _context(*, collection_status: str, system_status: str, metric_status: str) -> AlertEvaluationContext:
    device = SimpleNamespace(id=8, name="NAS Utama", device_type="nas")
    metrics = {
        (8, "nas_snmp_collection_status"): SimpleNamespace(metric_value=collection_status, status="ok" if collection_status == "ok" else "warning"),
        (8, "nas_system_status"): SimpleNamespace(metric_value=system_status, status=metric_status),
    }
    return AlertEvaluationContext(
        device=device,
        latest_metrics=metrics,
        thresholds={"nas_system_temperature_warning": 55, "nas_disk_temperature_warning": 55},
        threshold_overrides=[],
        expected_alerts={},
        printer_uptime_history_by_device={},
        internet_service_history_by_device={},
        metric_history_by_device={},
    )


def test_nas_collection_failure_creates_only_monitoring_alert():
    context = _context(collection_status="timeout", system_status="unknown", metric_status="warning")

    evaluate_nas_domain_alerts(context)

    assert set(context.expected_alerts) == {(8, "nas_snmp_collection_degraded")}


def test_nas_unknown_scalar_does_not_create_hardware_alert():
    context = _context(collection_status="ok", system_status="unknown", metric_status="warning")

    evaluate_nas_domain_alerts(context)

    assert context.expected_alerts == {}


def test_nas_confirmed_failed_scalar_creates_hardware_alert():
    context = _context(collection_status="ok", system_status="failed", metric_status="error")

    evaluate_nas_domain_alerts(context)

    assert (8, "nas_system_status_problem") in context.expected_alerts
