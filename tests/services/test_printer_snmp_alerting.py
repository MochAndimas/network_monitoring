"""Unit tests for separating printer SNMP collection failures from printer faults."""

from __future__ import annotations

from backend.app.models.device import Device
from backend.app.models.metric import Metric

from backend.app.alerting.engine_parts.evaluation_context import AlertEvaluationContext
from backend.app.alerting.engine_parts.rule_evaluators import evaluate_expected_alerts_for_device


def _context(*, collection_status: str, paper_status: str = "ok") -> AlertEvaluationContext:
    device = Device(id=7, name="Printer Meeting", device_type="printer")
    metrics = {
        (7, "printer_snmp_collection_status"): Metric(
            metric_value=collection_status, status="ok" if collection_status == "ok" else "warning"
        ),
        (7, "printer_paper_status"): Metric(
            metric_value=paper_status, status="warning" if paper_status != "ok" else "ok"
        ),
    }
    return AlertEvaluationContext(
        device=device,
        latest_metrics=metrics,
        thresholds={},
        threshold_overrides=[],
        expected_alerts={},
        printer_uptime_history_by_device={},
        internet_service_history_by_device={},
        metric_history_by_device={},
    )


def test_printer_collection_failure_creates_only_monitoring_alert():
    context = _context(collection_status="timeout", paper_status="unavailable")

    evaluate_expected_alerts_for_device(context)

    assert set(context.expected_alerts) == {(7, "printer_snmp_collection_degraded")}
    assert context.expected_alerts[(7, "printer_snmp_collection_degraded")]["severity"] == "warning"


def test_printer_business_alerts_still_run_when_collection_is_healthy():
    context = _context(collection_status="ok", paper_status="low")

    evaluate_expected_alerts_for_device(context)

    assert (7, "printer_paper_issue") in context.expected_alerts
