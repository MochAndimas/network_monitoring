"""Define module logic for `dashboard/components/auth_bridge.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT = components.declare_component(
    "dashboard_auth_bridge",
    path=str(Path(__file__).resolve().parent / "auth_bridge_frontend"),
)


def auth_bridge(*, action: str, host: str, request_id: str, payload: dict | None = None, key: str):
    """Return auth bridge.

    Args:
        action: Parameter input untuk routine ini.
        host: Parameter input untuk routine ini.
        request_id: Parameter input untuk routine ini.
        payload: Parameter input untuk routine ini.
        key: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return _COMPONENT(
        action=action,
        host=host,
        request_id=request_id,
        payload=payload or {},
        key=key,
        default=None,
    )
