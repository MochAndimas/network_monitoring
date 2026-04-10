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
    st.sidebar.markdown("### Live Refresh")
    auto_refresh = st.sidebar.toggle(
        "Auto Refresh",
        value=default_enabled,
        key=f"{page_key}_auto_refresh",
        help="Kalau aktif, halaman ini akan ambil data terbaru secara berkala.",
    )
    interval_seconds = st.sidebar.selectbox(
        "Refresh Interval",
        options=REFRESH_INTERVAL_OPTIONS,
        index=REFRESH_INTERVAL_OPTIONS.index(default_interval),
        key=f"{page_key}_refresh_interval",
        format_func=lambda value: f"{value} detik",
        help="Pilih seberapa sering dashboard mengambil update baru dari backend.",
    )
    return auto_refresh, int(interval_seconds)


def live_status_text(auto_refresh: bool, interval_seconds: int) -> str:
    if auto_refresh:
        return f"Live refresh aktif. Data akan diperbarui tiap {interval_seconds} detik."
    return "Live refresh nonaktif. Gunakan tombol browser refresh kalau ingin update manual."


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
