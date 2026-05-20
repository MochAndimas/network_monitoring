"""Shared pytest collection rules."""

from __future__ import annotations

from pathlib import Path

import pytest

INTEGRATION_TEST_FILES = {
    Path("tests/services/test_auth_service.py"),
    Path("tests/services/test_retention_service.py"),
    Path("tests/services/test_transaction_boundary.py"),
}

SLOW_TEST_FILES = {
    Path("tests/api/dashboard_endpoints/test_auth_endpoints.py"),
    Path("tests/api/dashboard_endpoints/test_dashboard_core.py"),
    Path("tests/api/dashboard_endpoints/test_devices_metrics_endpoints.py"),
    Path("tests/api/dashboard_endpoints/test_run_cycle_and_security.py"),
    Path("tests/monitors/test_internet_monitor.py"),
    Path("tests/services/test_mysql_integration.py"),
    Path("tests/services/test_retention_service.py"),
    Path("tests/services/test_transaction_boundary.py"),
}

MYSQL_TEST_FILES = {
    Path("tests/services/test_mysql_integration.py"),
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Attach coarse test-suite markers from stable test paths."""
    root = Path(str(config.rootpath))
    for item in items:
        test_path = Path(str(item.path))
        relative_path = _relative_test_path(test_path, root)

        if _is_integration_test(relative_path):
            item.add_marker(pytest.mark.integration)
        if relative_path in SLOW_TEST_FILES:
            item.add_marker(pytest.mark.slow)
        if relative_path in MYSQL_TEST_FILES:
            item.add_marker(pytest.mark.mysql)
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.slow)

        if not any(item.get_closest_marker(name) for name in ("integration", "mysql")):
            item.add_marker(pytest.mark.unit)


def _relative_test_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _is_integration_test(path: Path) -> bool:
    return (
        path.parts[:3] == ("tests", "api", "dashboard_endpoints")
        or path.parts[:2] == ("tests", "monitors")
        or path in INTEGRATION_TEST_FILES
        or path in MYSQL_TEST_FILES
    )
