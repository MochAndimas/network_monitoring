from urllib.parse import parse_qs, urlsplit

from dashboard.pages.live_monitoring.body import (
    _history_context_path,
    _selected_trend_metric_names,
    _trend_limit_for_chart_window,
)


def test_history_context_path_preserves_repeated_trend_metric_names():
    path = _history_context_path(
        "/metrics/history/live",
        {
            "device_id": 1,
            "include_selected_device_trend": "true",
            "trend_metric_names": ["ping", "packet_loss", "jitter"],
            "trend_limit": 200,
        },
    )

    parsed_query = parse_qs(urlsplit(path).query)

    assert parsed_query["trend_metric_names"] == ["ping", "packet_loss", "jitter"]
    assert parsed_query["include_selected_device_trend"] == ["true"]


def test_selected_trend_metric_names_uses_all_generic_device_metrics():
    metric_names = _selected_trend_metric_names(
        selected_metric="All Metrics",
        selected_device_type="access_point",
        selected_is_mikrotik=False,
        metric_name_options=["ping", "packet_loss", "jitter"],
    )

    assert metric_names == ["ping", "packet_loss", "jitter"]


def test_trend_limit_for_chart_window_expands_twelve_hour_budget():
    assert _trend_limit_for_chart_window(200, "12 jam") == 900
