"""Define test module behavior for `tests/services/test_benchmark_endpoints.py`.

This module contains automated regression and validation scenarios.
"""

from scripts.benchmark_endpoints import _resolve_thresholds


def test_resolve_thresholds_uses_profile_defaults():
    """Validate that resolve thresholds uses profile defaults.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    assert _resolve_thresholds(profile="ci", max_p95_ms=0.0, max_max_ms=0.0) == (1500.0, 2500.0)
    assert _resolve_thresholds(profile="strict", max_p95_ms=0.0, max_max_ms=0.0) == (1000.0, 2000.0)


def test_resolve_thresholds_custom_keeps_explicit_values():
    """Validate that resolve thresholds custom keeps explicit values.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    assert _resolve_thresholds(profile="custom", max_p95_ms=123.0, max_max_ms=456.0) == (123.0, 456.0)
