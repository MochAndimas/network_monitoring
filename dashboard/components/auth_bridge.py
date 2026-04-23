"""Provide shared Streamlit dashboard UI and API helpers for the network monitoring project."""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT = components.declare_component(
    "dashboard_auth_bridge",
    path=str(Path(__file__).resolve().parent / "auth_bridge_frontend"),
)


def auth_bridge(*, action: str, host: str, request_id: str, payload: dict | None = None, key: str):
    return _COMPONENT(
        action=action,
        host=host,
        request_id=request_id,
        payload=payload or {},
        key=key,
        default=None,
    )
