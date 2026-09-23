"""Regression coverage for diagnostics and guards exercised by security cleanup."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app.alerting.engine_parts.evaluation_context import AlertEvaluationContext
from backend.app.alerting.engine_parts.rule_evaluators import evaluate_internet_service_alerts
from backend.app.models.device import Device
from backend.app.models.metric import Metric
from backend.app.monitors.device import nas_snmp, printer_snmp
from backend.app.services import pipeline_control
from tests.test_utils import run


@pytest.mark.parametrize("module", [nas_snmp, printer_snmp])
def test_snmp_cleanup_failure_preserves_read_result_and_hides_exception(monkeypatch, caplog, module):
    close = Mock(side_effect=RuntimeError("private-community-value"))
    monkeypatch.setattr(
        module, "SnmpEngine", lambda: SimpleNamespace(transport_dispatcher=SimpleNamespace(close_dispatcher=close))
    )
    monkeypatch.setattr(module, "UdpTransportTarget", SimpleNamespace(create=AsyncMock(return_value=object())))
    monkeypatch.setattr(module, "get_cmd", AsyncMock(return_value=(None, None, None, [(None, "42")])))
    kwargs = {"mp_model": 1} if module is printer_snmp else {}
    with caplog.at_level(logging.DEBUG, logger=module.__name__):
        result = run(module._snmp_get_value("192.0.2.1", "private-community-value", "1.3.6.1.2.1.1.3.0", **kwargs))
    assert result.value == "42"
    close.assert_called_once()
    assert "Transport cleanup failed" in caplog.text
    assert "private-community-value" not in caplog.text


@pytest.mark.parametrize(
    "metric_name, threshold_key",
    [
        ("dns_resolution_time", "dns_resolution_warning"),
        ("http_response_time", "http_response_warning"),
    ],
)
def test_matching_rule_rejects_non_numeric_latest_metric(metric_name, threshold_key):
    context = AlertEvaluationContext(
        device=Device(id=1, name="ISP", device_type="internet_target"),
        latest_metrics={(1, metric_name): Metric(metric_value="unavailable", status="warning")},
        thresholds={threshold_key: 50},
        threshold_overrides=[],
        expected_alerts={},
        printer_uptime_history_by_device={},
        metric_history_by_device={},
        internet_service_history_by_device={1: {metric_name: [Metric(metric_value="100"), Metric(metric_value="120")]}},
    )
    with pytest.raises(ValueError, match="must be numeric"):
        evaluate_internet_service_alerts(context)
    assert context.expected_alerts == {}


def test_long_lock_name_keeps_existing_cross_process_identity(monkeypatch):
    # Fixed compatibility vector: changing this identifier could split the lock
    # between old and new workers during a rollout.
    monkeypatch.setattr(pipeline_control.settings, "monitoring_lock_name", "x" * 64)
    assert pipeline_control._scoped_lock_name("alerts") == "x" * 47 + "." + "42c6a0f763643318"
