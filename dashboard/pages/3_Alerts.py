"""Provide Streamlit dashboard page rendering for the network monitoring project."""

import altair as alt
import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp
from components.ui import normalize_status_label, render_kpi_cards, render_meta_row, render_page_header, status_priority

st.set_page_config(page_title="Alerts", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "Alerts",
    "Ringkasan alert aktif untuk prioritasi penanganan gangguan.",
)

filter_col1, filter_col2 = st.columns([1, 2])
severity_filter = filter_col1.selectbox(
    "Tingkat Alert",
    options=["All", "Critical", "High", "Warning", "Error", "Down", "Unknown"],
    index=0,
    format_func=lambda value: "Semua" if value == "All" else str(value),
)
search_filter = filter_col2.text_input("Cari", placeholder="Filter berdasarkan device atau pesan")
with st.expander("Filter Lanjutan"):
    adv_col1, adv_col2 = st.columns(2)
    sort_mode = adv_col1.selectbox("Urutkan", options=["Terbaru", "Tingkat Tertinggi"], index=0)
    max_rows = adv_col2.selectbox("Maks. Baris Detail", options=[25, 50, 100, 200], index=1)

auto_refresh, interval_seconds = refresh_controls("alerts", default_enabled=True, default_interval=15)


def _render_alerts_body() -> None:
    """Render alerts body for Streamlit dashboard page rendering.

    Returns:
        None. The routine is executed for its side effects.
    """
    alerts = get_json("/alerts/active", [])
    render_meta_row(
        [
            ("Refresh Otomatis", live_status_text(auto_refresh, interval_seconds)),
            ("Terakhir Diperbarui", rendered_at_label()),
            ("Filter Tingkat", severity_filter),
            ("Urutan", sort_mode),
        ]
    )

    if not alerts:
        st.success("Tidak ada alert aktif. Pantau kembali pada siklus monitoring berikutnya.")
        return

    dataframe = pd.DataFrame(alerts)
    if "created_at" in dataframe.columns:
        dataframe["created_at"] = to_wib_timestamp(dataframe["created_at"])
        dataframe["created_at_wib"] = dataframe["created_at"].apply(format_wib_timestamp)
    else:
        dataframe["created_at"] = pd.NaT
        dataframe["created_at_wib"] = "-"
    if "resolved_at" in dataframe.columns:
        dataframe["resolved_at"] = to_wib_timestamp(dataframe["resolved_at"])
        dataframe["resolved_at_wib"] = dataframe["resolved_at"].apply(format_wib_timestamp)
    else:
        dataframe["resolved_at_wib"] = "-"

    if "severity" in dataframe.columns:
        dataframe["severity"] = dataframe["severity"].map(normalize_status_label)
    else:
        dataframe["severity"] = "Unknown"
    dataframe["severity_priority"] = dataframe["severity"].map(status_priority)
    dataframe["device_name"] = dataframe["device_name"].fillna("-") if "device_name" in dataframe.columns else "-"
    dataframe["message"] = dataframe["message"].fillna("-") if "message" in dataframe.columns else "-"

    filtered_frame = dataframe.copy()
    if severity_filter != "All":
        filtered_frame = filtered_frame[filtered_frame["severity"].str.lower() == severity_filter.lower()]
    if search_filter.strip():
        needle = search_filter.strip().lower()
        filtered_frame = filtered_frame[
            filtered_frame["device_name"].str.lower().str.contains(needle, na=False)
            | filtered_frame["message"].str.lower().str.contains(needle, na=False)
        ]

    if filtered_frame.empty:
        st.info("Tidak ada alert yang cocok dengan filter. Ubah severity atau kata kunci pencarian.")
        return

    if sort_mode == "Tingkat Tertinggi":
        filtered_frame = filtered_frame.sort_values(["severity_priority", "created_at"], ascending=[True, False])
    else:
        filtered_frame = filtered_frame.sort_values("created_at", ascending=False)

    critical_like = {"critical", "high", "error", "down"}
    critical_count = int(filtered_frame["severity"].str.lower().isin(critical_like).sum())
    affected_devices = int(filtered_frame["device_name"].nunique())
    oldest_alert = filtered_frame["created_at"].min() if not filtered_frame.empty else None
    oldest_label = format_wib_timestamp(oldest_alert) if oldest_alert is not None and pd.notna(oldest_alert) else "-"

    render_kpi_cards(
        [
            ("Total Alert Aktif", int(len(filtered_frame)), None),
            ("Alert Critical / High", critical_count, None),
            ("Device Terdampak", affected_devices, None),
            ("Alert Tertua (WIB)", oldest_label, None),
        ],
        columns_per_row=4,
    )

    severity_counts = (
        filtered_frame["severity"]
        .value_counts()
        .rename_axis("Tingkat")
        .reset_index(name="Jumlah")
    )
    severity_counts["Priority"] = severity_counts["Tingkat"].map(status_priority)
    severity_counts = severity_counts.sort_values(["Priority", "Jumlah", "Tingkat"], ascending=[True, False, True])
    top_devices = (
        filtered_frame["device_name"]
        .value_counts()
        .rename_axis("Device")
        .reset_index(name="Alerts")
        .sort_values("Alerts", ascending=False)
        .head(10)
    )

    chart_col, table_col = st.columns([1, 1])
    with chart_col:
        st.markdown("### Distribusi Tingkat Alert")
        severity_chart = (
            alt.Chart(severity_counts)
            .mark_bar()
            .encode(
                x=alt.X("Jumlah:Q", title="Jumlah Alert"),
                y=alt.Y("Tingkat:N", sort="-x", title="Tingkat"),
                tooltip=[alt.Tooltip("Tingkat:N", title="Tingkat"), alt.Tooltip("Jumlah:Q", title="Jumlah")],
            )
            .properties(height=260)
        )
        st.altair_chart(severity_chart, width="stretch")
        st.dataframe(
            severity_counts[["Tingkat", "Jumlah"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Tingkat": st.column_config.TextColumn("Tingkat", width="small"),
                "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
            },
        )
    with table_col:
        st.markdown("### Device Paling Terdampak")
        device_chart = (
            alt.Chart(top_devices)
            .mark_bar()
            .encode(
                x=alt.X("Alerts:Q", title="Jumlah Alert"),
                y=alt.Y("Device:N", sort="-x", title="Device"),
                tooltip=[alt.Tooltip("Device:N", title="Device"), alt.Tooltip("Alerts:Q", title="Jumlah")],
            )
            .properties(height=260)
        )
        st.altair_chart(device_chart, width="stretch")
        st.dataframe(
            top_devices,
            width="stretch",
            hide_index=True,
            column_config={
                "Device": st.column_config.TextColumn("Device", width="large"),
                "Alerts": st.column_config.NumberColumn("Alerts", width="small", format="%d"),
            },
        )

    st.markdown("### Detail Alert Aktif")
    detail_columns = ["created_at_wib", "device_name", "severity", "message"]
    if "metric_name" in filtered_frame.columns:
        detail_columns.insert(3, "metric_name")
    detail_frame = filtered_frame[detail_columns].rename(
        columns={
            "created_at_wib": "Dibuat (WIB)",
            "device_name": "Device",
            "severity": "Tingkat",
            "metric_name": "Metrik",
            "message": "Pesan",
        }
    )
    st.dataframe(
        detail_frame.head(int(max_rows)),
        width="stretch",
        hide_index=True,
        column_config={
            "Dibuat (WIB)": st.column_config.TextColumn("Dibuat (WIB)", width="medium"),
            "Device": st.column_config.TextColumn("Device", width="medium"),
            "Tingkat": st.column_config.TextColumn("Tingkat", width="small"),
            "Metrik": st.column_config.TextColumn("Metrik", width="small"),
            "Pesan": st.column_config.TextColumn("Pesan", width="large"),
        },
    )
    st.markdown("")
    st.caption("Tip: gunakan filter severity dan kata kunci untuk mempercepat triase alert.")


render_live_section(auto_refresh, interval_seconds, _render_alerts_body)
