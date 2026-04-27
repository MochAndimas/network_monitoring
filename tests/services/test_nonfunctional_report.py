"""Define test module behavior for `tests/services/test_nonfunctional_report.py`.

This module contains automated regression and validation scenarios.
"""

from __future__ import annotations

from datetime import date, datetime

from scripts.nonfunctional_report import (
    _build_sla_summary,
    _build_triage_markdown,
    _build_weekly_sla_markdown,
    _week_range,
)


def test_week_range_returns_monday_to_sunday_window():
    """Validate that week range returns monday to sunday window.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    week_start, week_end = _week_range(date(2026, 4, 24))
    assert week_start.isoformat() == "2026-04-20"
    assert week_end.isoformat() == "2026-04-26"


def test_build_triage_markdown_includes_gate_table_and_checklist():
    """Validate that build triage markdown includes gate table and checklist.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    benchmark_payload = {
        "results": [{"path": "/devices/paged", "p95_ms": 120.0, "max_ms": 240.0}],
        "failures": [],
    }
    concurrency_payload = {
        "results": [{"path": "/health/live", "p95_ms": 20.0, "max_ms": 35.0, "failures": []}],
        "failures": [],
    }
    observability_payload: dict[str, list] = {
        "missing_requests": [],
        "missing_rows": [],
    }

    markdown = _build_triage_markdown(
        benchmark_payload=benchmark_payload,
        concurrency_payload=concurrency_payload,
        observability_payload=observability_payload,
        generated_at=datetime(2026, 4, 24, 10, 0, 0),
    )

    assert "# Non-Functional Triage Summary" in markdown
    assert "| Benchmark regression | PASS | failures=0 |" in markdown
    assert "## Triage Checklist (Standar)" in markdown
    assert "`/devices/paged`" in markdown


def test_build_sla_summary_calculates_baseline_percentages():
    """Validate that build sla summary calculates baseline percentages.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    benchmark_payload = {
        "thresholds": {"max_p95_ms": 1500.0, "max_max_ms": 2500.0},
        "results": [
            {"path": "/devices/paged", "p95_ms": 100.0, "max_ms": 300.0},
            {"path": "/metrics/history/paged", "p95_ms": 2000.0, "max_ms": 3000.0},
        ],
        "failures": ["breach"],
    }
    concurrency_payload = {
        "thresholds": {"max_p95_ms": 1500.0, "max_max_ms": 2500.0},
        "results": [
            {"path": "/health/live", "p95_ms": 20.0, "max_ms": 45.0, "requests": 10, "failures": []},
            {"path": "/devices/paged", "p95_ms": 1600.0, "max_ms": 1900.0, "requests": 10, "failures": [500]},
        ],
        "failures": ["latency breach"],
    }
    observability_payload = {
        "expected_endpoints": ["/devices/paged", "/incidents/paged", "/metrics/history/paged"],
        "missing_requests": ["/incidents/paged"],
        "missing_rows": [],
    }

    summary = _build_sla_summary(
        benchmark_payload=benchmark_payload,
        concurrency_payload=concurrency_payload,
        observability_payload=observability_payload,
        generated_day=date(2026, 4, 24),
    )

    signals = summary["signals"]
    assert signals["benchmark_latency_compliance_pct"] == 50.0
    assert signals["concurrency_latency_compliance_pct"] == 50.0
    assert signals["concurrency_request_success_pct"] == 95.0
    assert signals["observability_coverage_pct"] == 66.67


def test_build_weekly_sla_markdown_renders_expected_sections():
    """Validate that build weekly sla markdown renders expected sections.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    payload = {
        "generated_day": "2026-04-24",
        "week_start": "2026-04-20",
        "week_end": "2026-04-26",
        "signals": {
            "benchmark_latency_compliance_pct": 88.0,
            "concurrency_latency_compliance_pct": 90.0,
            "concurrency_request_success_pct": 99.5,
            "observability_coverage_pct": 100.0,
        },
        "raw_counts": {
            "benchmark_endpoints_passed": 11,
            "benchmark_endpoints_total": 12,
            "concurrency_paths_passed": 5,
            "concurrency_paths_total": 5,
            "concurrency_requests_failed": 0,
            "concurrency_requests_total": 50,
            "observability_endpoints_covered": 6,
            "observability_expected_endpoints": 6,
        },
    }

    markdown = _build_weekly_sla_markdown(payload)

    assert "# Weekly Baseline SLA Report" in markdown
    assert "Week range: 2026-04-20 -> 2026-04-26" in markdown
    assert "Benchmark latency compliance: 88.00%" in markdown
