"""Reusable Streamlit session-state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Hashable


def sync_filter_page(
    session_state: MutableMapping[str, object],
    *,
    signature_key: str,
    page_key: str,
    signature: Hashable,
) -> bool:
    """Reset a page to one when its normalized filter signature changes."""
    if session_state.get(signature_key) == signature:
        return False
    session_state[signature_key] = signature
    session_state[page_key] = 1
    return True


def clamp_page(value: object, total_pages: int) -> int:
    """Return a valid one-based page number."""
    safe_total = max(int(total_pages), 1)
    try:
        page = int(value or 1)
    except (TypeError, ValueError):
        page = 1
    return min(max(page, 1), safe_total)
