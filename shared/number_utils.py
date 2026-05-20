"""Shared helpers for number utils."""

from __future__ import annotations


from typing import Any


def safe_float(value: Any) -> float | None:
    """Convert an arbitrary value to ``float`` without raising conversion errors.

    Args:
        value: Any value that may contain numeric content.

    Returns:
        Parsed floating-point number when conversion succeeds, otherwise ``None``.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

