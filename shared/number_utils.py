"""Numeric conversion helpers shared across application layers."""

from __future__ import annotations


def safe_float(value) -> float | None:
    """Convert value to float, returning None when conversion fails."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

