"""Canonical, credential-safe contracts shared by monitoring collectors."""

from __future__ import annotations

from typing import Final


COLLECTION_STATUS_VALUES: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "timeout",
        "authentication_failed",
        "connection_failed",
        "unsupported_oid",
        "protocol_error",
        "invalid_response",
        "rate_limited",
        "configuration_missing",
        "collector_error",
    }
)


def normalize_collection_status(value: object, *, fallback: str = "collector_error") -> str:
    """Return a known status without preserving raw backend or credential text."""
    normalized = str(value or "").strip().lower()
    return normalized if normalized in COLLECTION_STATUS_VALUES else fallback


def collection_metric_status(collection_status: object) -> str:
    """Map a collection result to the persisted metric severity contract."""
    return "ok" if normalize_collection_status(collection_status) == "ok" else "warning"


def classify_snmp_error(error_message: object) -> str:
    """Classify pysnmp errors into safe categories without returning the original text."""
    normalized = str(error_message or "").lower()
    if "timeout" in normalized or "no snmp response" in normalized:
        return "timeout"
    if "authorization" in normalized or "authentication" in normalized or "wrong community" in normalized:
        return "authentication_failed"
    if "no such" in normalized or "unknown object" in normalized:
        return "unsupported_oid"
    if "too many" in normalized or "rate limit" in normalized:
        return "rate_limited"
    return "connection_failed"


__all__ = [
    "COLLECTION_STATUS_VALUES",
    "classify_snmp_error",
    "collection_metric_status",
    "normalize_collection_status",
]
