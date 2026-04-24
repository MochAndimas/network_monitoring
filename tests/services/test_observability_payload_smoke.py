"""Provide regression tests for observability payload smoke helpers."""

from scripts.observability_payload_smoke import (
    _find_missing_request_coverage,
    _find_missing_rows_coverage,
    _parse_metric_lines,
)


def test_parse_metric_lines_extracts_labels_and_values():
    metrics_text = """
    # HELP sample
    network_monitoring_api_payload_requests_total{endpoint="/devices/paged",scope="all"} 2
    network_monitoring_api_payload_requests_total{endpoint="/alerts/active/paged",scope="active"} 1
    """

    records = _parse_metric_lines(metrics_text, "network_monitoring_api_payload_requests_total")

    assert len(records) == 2
    assert records[0][0]["endpoint"] == "/devices/paged"
    assert records[0][0]["scope"] == "all"
    assert records[0][1] == 2.0


def test_find_missing_request_coverage_reports_unseen_endpoint():
    metrics_text = """
    network_monitoring_api_payload_requests_total{endpoint="/devices/paged",scope="all"} 1
    """
    missing = _find_missing_request_coverage(metrics_text, ["/devices/paged", "/incidents/paged"])
    assert missing == ["/incidents/paged"]


def test_find_missing_rows_coverage_requires_items_section():
    metrics_text = """
    network_monitoring_api_payload_rows_total{endpoint="/devices/paged",scope="all",section="items"} 100
    network_monitoring_api_payload_rows_total{endpoint="/incidents/paged",scope="active",section="summary"} 10
    """
    missing = _find_missing_rows_coverage(metrics_text, ["/devices/paged", "/incidents/paged"])
    assert missing == ["/incidents/paged"]
