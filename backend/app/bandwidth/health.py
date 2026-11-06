"""Shared freshness contract for inventory, ingestion health, and diagnostics."""

WORKER_HEARTBEAT_MAX_AGE_SECONDS = 45


def observation_is_fresh(
    observed_ns: int, now_ns: int, max_age_seconds: int = WORKER_HEARTBEAT_MAX_AGE_SECONDS
) -> bool:
    """Reject future timestamps as well as stale observations."""
    return 0 <= now_ns - observed_ns <= max_age_seconds * 10**9
