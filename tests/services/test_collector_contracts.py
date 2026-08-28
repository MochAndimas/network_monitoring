"""Regression tests for shared collector status vocabulary."""

from backend.app.monitors.contracts import classify_snmp_error, collection_metric_status, normalize_collection_status


def test_collection_status_normalization_never_returns_raw_error_text():
    assert normalize_collection_status("timeout") == "timeout"
    assert normalize_collection_status("password=not-safe") == "collector_error"
    assert collection_metric_status("ok") == "ok"
    assert collection_metric_status("timeout") == "warning"


def test_snmp_error_categories_are_actionable_and_safe():
    assert classify_snmp_error("No SNMP response received before timeout") == "timeout"
    assert classify_snmp_error("Wrong community string") == "authentication_failed"
    assert classify_snmp_error("No such object available") == "unsupported_oid"
