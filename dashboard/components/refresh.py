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
    if auto_refresh:
        return f"Aktif, data diperbarui setiap {interval_seconds} detik."
    return "Nonaktif, gunakan refresh browser untuk memperbarui data."


def rendered_at_label() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")


def render_live_section(auto_refresh: bool, interval_seconds: int, render_fn) -> None:
    if auto_refresh:
        @st.fragment(run_every=f"{interval_seconds}s")
        def _live_fragment():
            render_fn()

        _live_fragment()
        return

    render_fn()
