"""Unit tests for Printer MIB value normalization."""

from backend.app.monitors.device.printer_snmp import _build_paper_detail_metric, _build_printer_status_metric, _build_toner_metrics


def test_paper_detail_treats_negative_three_as_available_with_unknown_quantity():
    """Printer MIB -3 means one or more sheets remain, rather than empty."""
    metric = _build_paper_detail_metric(
        {
            "printer_input_name": "Drawer 1",
            "printer_input_current_level": -3,
            "printer_input_max_capacity": 100,
        }
    )

    assert metric.metric_value == "Drawer 1: tersedia (jumlah tidak diketahui)"
    assert metric.status == "ok"


def test_toner_metrics_include_only_reported_cmyk_supplies():
    """Color printers emit CMYK; monochrome printers do not get missing-color warnings."""
    metrics = _build_toner_metrics(
        {
            "printer_toner_black_colorant_raw": "black",
            "printer_toner_black_level_raw": 16,
            "printer_toner_cyan_colorant_raw": "cyan",
            "printer_toner_cyan_level_raw": 20,
            "printer_toner_magenta_colorant_raw": "magenta",
            "printer_toner_magenta_level_raw": 20,
            "printer_toner_yellow_colorant_raw": "yellow",
            "printer_toner_yellow_level_raw": 20,
        }
    )

    assert [(metric.metric_name, metric.metric_value, metric.status) for metric in metrics] == [
        ("printer_toner_black_percent", "16", "warning"),
        ("printer_toner_cyan_percent", "20", "warning"),
        ("printer_toner_magenta_percent", "20", "warning"),
        ("printer_toner_yellow_percent", "20", "warning"),
    ]


def test_other_printer_status_is_not_an_actionable_warning():
    """A valid but unspecific Host-Resources status should not create an anomaly."""
    metric = _build_printer_status_metric({"printer_status_code": 1})

    assert metric.metric_value == "other"
    assert metric.status == "up"
