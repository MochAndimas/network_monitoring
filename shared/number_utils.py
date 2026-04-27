"""Define module logic for `shared/number_utils.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations


def safe_float(value) -> float | None:
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

