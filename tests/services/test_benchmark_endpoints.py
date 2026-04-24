"""Provide regression tests for benchmark helper logic."""

from scripts.benchmark_endpoints import _resolve_thresholds


def test_resolve_thresholds_uses_profile_defaults():
    assert _resolve_thresholds(profile="ci", max_p95_ms=0.0, max_max_ms=0.0) == (1500.0, 2500.0)
    assert _resolve_thresholds(profile="strict", max_p95_ms=0.0, max_max_ms=0.0) == (1000.0, 2000.0)


def test_resolve_thresholds_custom_keeps_explicit_values():
    assert _resolve_thresholds(profile="custom", max_p95_ms=123.0, max_max_ms=456.0) == (123.0, 456.0)
