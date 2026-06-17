"""Performance budget definitions for dashboard/API endpoints."""

from __future__ import annotations


DASHBOARD_PERFORMANCE_BUDGETS = [
    {
        "endpoint": "/dashboard/summary",
        "max_p95_ms": 1000.0,
        "max_payload_rows": 50,
        "notes": "Overview cards and recent operational rows.",
    },
    {
        "endpoint": "/devices/paged",
        "max_p95_ms": 1200.0,
        "max_payload_rows": 500,
        "notes": "Server-side paged device inventory.",
    },
    {
        "endpoint": "/alerts/active/paged",
        "max_p95_ms": 1000.0,
        "max_payload_rows": 500,
        "notes": "Active alert triage with severity/site/search filters.",
    },
    {
        "endpoint": "/incidents/paged",
        "max_p95_ms": 1200.0,
        "max_payload_rows": 500,
        "notes": "Incident workflow list with site/search filters.",
    },
    {
        "endpoint": "/metrics/history/live",
        "max_p95_ms": 1500.0,
        "max_payload_rows": 2000,
        "notes": "Live dashboard bounded to recent raw metrics.",
    },
    {
        "endpoint": "/metrics/long-term-explorer",
        "max_p95_ms": 1500.0,
        "max_payload_rows": 866,
        "notes": "Long-term trends from rollup/archive tables, not raw metrics.",
    },
]


def list_performance_budgets() -> list[dict]:
    """Return dashboard/API endpoint performance budgets."""
    return list(DASHBOARD_PERFORMANCE_BUDGETS)
