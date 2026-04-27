"""Define test module behavior for `tests/services/test_concurrency_smoke.py`.

This module contains automated regression and validation scenarios.
"""

from scripts.concurrency_smoke import _collect_gate_failures, _resolve_thresholds, _summarize_results


def test_summarize_results_builds_expected_metrics():
    """Validate that summarize results builds expected metrics.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    summary = _summarize_results(
        path="/health/live",
        results=[
            (200, 10.0),
            (200, 20.0),
            (500, 40.0),
            (200, 15.0),
        ],
    )

    assert summary["path"] == "/health/live"
    assert summary["requests"] == 4
    assert summary["avg_ms"] == 21.25
    assert summary["p95_ms"] == 20.0
    assert summary["max_ms"] == 40.0
    assert summary["failures"] == [500]


def test_collect_gate_failures_returns_status_and_latency_breaches():
    """Validate that collect gate failures returns status and latency breaches.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    result = {
        "path": "/metrics/history/paged",
        "p95_ms": 1600.0,
        "max_ms": 2600.0,
        "failures": [401, 500],
    }

    failures = _collect_gate_failures(
        result=result,
        max_p95_ms=1500.0,
        max_max_ms=2500.0,
    )

    assert len(failures) == 3
    assert "/metrics/history/paged returned non-success statuses" in failures[0]
    assert "exceeded p95 threshold" in failures[1]
    assert "exceeded max threshold" in failures[2]


def test_resolve_thresholds_uses_expected_profiles():
    """Validate that resolve thresholds uses expected profiles.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    assert _resolve_thresholds(profile="ci", max_p95_ms=0.0, max_max_ms=0.0) == (1500.0, 2500.0)
    assert _resolve_thresholds(profile="strict", max_p95_ms=0.0, max_max_ms=0.0) == (1000.0, 2000.0)
    assert _resolve_thresholds(profile="custom", max_p95_ms=111.0, max_max_ms=222.0) == (111.0, 222.0)
