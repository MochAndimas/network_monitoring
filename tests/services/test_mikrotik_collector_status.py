"""Unit tests for RouterOS API failure classification."""

from backend.app.monitors.mikrotik.parts.impl import _mikrotik_api_error_category


def test_mikrotik_api_timeout_is_classified_without_raw_error():
    assert _mikrotik_api_error_category(TimeoutError("request timed out")) == "timeout"


def test_mikrotik_api_auth_failure_is_classified_without_raw_error():
    assert _mikrotik_api_error_category(RuntimeError("invalid username or password")) == "authentication_failed"


def test_mikrotik_api_unrecognized_failure_is_collector_error():
    assert _mikrotik_api_error_category(RuntimeError("unexpected library issue")) == "collector_error"
