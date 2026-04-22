"""Provide shared Streamlit dashboard UI and API helpers for the network monitoring project."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st


REFRESH_INTERVAL_OPTIONS = [5, 10, 15, 30, 60]
WIB = ZoneInfo("Asia/Jakarta")


def refresh_controls(
    page_key: str,
    *,
    default_enabled: bool = True,
    default_interval: int = 15,
) -> tuple[bool, int]:
    """Refresh controls for shared Streamlit dashboard UI and API helpers.

    Args:
        page_key: page key value used by this routine (type `str`).
        default_enabled: default enabled keyword value used by this routine (type `bool`, optional).
        default_interval: default interval keyword value used by this routine (type `int`, optional).

    Returns:
        `tuple[bool, int]` result produced by the routine.
    """
    st.sidebar.markdown("### Pembaruan Data")
    with st.sidebar.container(border=True):
        auto_refresh = st.toggle(
            "Refresh Otomatis",
            value=default_enabled,
            key=f"{page_key}_auto_refresh",
            help="Aktifkan untuk memuat data terbaru secara berkala.",
        )
        interval_seconds = st.selectbox(
            "Interval",
            options=REFRESH_INTERVAL_OPTIONS,
            index=REFRESH_INTERVAL_OPTIONS.index(default_interval),
            key=f"{page_key}_refresh_interval",
            format_func=lambda value: f"{value} detik",
            help="Tentukan jeda pembaruan data.",
        )
    return auto_refresh, int(interval_seconds)


def live_status_text(auto_refresh: bool, interval_seconds: int) -> str:
    """Handle live status text for shared Streamlit dashboard UI and API helpers.

    Args:
        auto_refresh: auto refresh value used by this routine (type `bool`).
        interval_seconds: interval seconds value used by this routine (type `int`).

    Returns:
        `str` result produced by the routine.
    """
    if auto_refresh:
        return f"Aktif, data diperbarui setiap {interval_seconds} detik."
    return "Nonaktif, gunakan refresh browser untuk memperbarui data."


def rendered_at_label() -> str:
    """Handle rendered at label for shared Streamlit dashboard UI and API helpers.

    Returns:
        `str` result produced by the routine.
    """
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")


def render_live_section(auto_refresh: bool, interval_seconds: int, render_fn) -> None:
    """Render live section for shared Streamlit dashboard UI and API helpers.

    Args:
        auto_refresh: auto refresh value used by this routine (type `bool`).
        interval_seconds: interval seconds value used by this routine (type `int`).
        render_fn: render fn value used by this routine.

    Returns:
        None. The routine is executed for its side effects.
    """
    if auto_refresh:
        @st.fragment(run_every=f"{interval_seconds}s")
        def _live_fragment():
            """Handle the internal live fragment helper logic for shared Streamlit dashboard UI and API helpers.

            Returns:
                The computed result, response payload, or side-effect outcome for the caller.
            """
            render_fn()

        _live_fragment()
        return

    render_fn()
