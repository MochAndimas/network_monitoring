import altair as alt
import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp
from components.ui import normalize_status_label, render_kpi_cards, render_meta_row, render_page_header, status_priority

st.set_page_config(page_title="Incidents", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "Incidents",
    "Pelacakan insiden aktif dan selesai untuk melihat dampak operasional serta durasi gangguan.",
)

filter_col1, filter_col2 = st.columns([1, 2])
status_filter = filter_col1.selectbox("Incident Status", options=["All", "active", "resolved"], index=0)
search_filter = filter_col2.text_input("Cari", placeholder="Filter berdasarkan device atau ringkasan")
with st.expander("Filter Lanjutan"):
    adv_col1, adv_col2 = st.columns(2)
    sort_mode = adv_col1.selectbox("Urutkan", options=["Terbaru", "Durasi Terpanjang", "Berdasarkan Status"], index=0)
    max_rows = adv_col2.selectbox("Maks. Baris Detail", options=[25, 50, 100, 200], index=1)
auto_refresh, interval_seconds = refresh_controls("incidents", default_enabled=True, default_interval=15)


def _duration_label(minutes_value: float | None) -> str:
    if minutes_value is None or pd.isna(minutes_value):
        return "-"
    minutes = int(minutes_value)
    hours, mins = divmod(minutes, 60)
    return f"{hours}j {mins}m" if hours else f"{mins}m"


def _render_incidents_body() -> None:
    path = "/incidents" if status_filter == "All" else f"/incidents?status={status_filter}"
    incidents = get_json(path, [])

    render_meta_row(
        [
            ("Refresh Otomatis", live_status_text(auto_refresh, interval_seconds)),
            ("Terakhir Diperbarui", rendered_at_label()),
            ("Filter Status", normalize_status_label(status_filter)),
            ("Urutan", sort_mode),
        ]
    )

    if not incidents:
        st.info("Belum ada incident yang tercatat.")
        return

    dataframe = pd.DataFrame(incidents)
    dataframe["device_name"] = dataframe["device_name"].fillna("-") if "device_name" in dataframe.columns else "-"
    dataframe["summary"] = dataframe["summary"].fillna("-") if "summary" in dataframe.columns else "-"
    if "status" in dataframe.columns:
        dataframe["status"] = dataframe["status"].map(normalize_status_label)
    else:
        dataframe["status"] = "Unknown"
    dataframe["status_priority"] = dataframe["status"].map(status_priority)

    if "started_at" in dataframe.columns:
        dataframe["started_at"] = to_wib_timestamp(dataframe["started_at"])
        dataframe["started_at_wib"] = dataframe["started_at"].apply(format_wib_timestamp)
    else:
        dataframe["started_at"] = pd.NaT
        dataframe["started_at_wib"] = "-"

    if "ended_at" in dataframe.columns:
        dataframe["ended_at"] = to_wib_timestamp(dataframe["ended_at"])
        dataframe["ended_at_wib"] = dataframe["ended_at"].apply(format_wib_timestamp)
    else:
        dataframe["ended_at"] = pd.NaT
        dataframe["ended_at_wib"] = "-"

    dataframe["duration_minutes"] = (
        (dataframe["ended_at"] - dataframe["started_at"]).dt.total_seconds().div(60)
        if "ended_at" in dataframe.columns and "started_at" in dataframe.columns
        else pd.Series(dtype=float)
    )
    dataframe["duration_label"] = dataframe["duration_minutes"].map(_duration_label)

    filtered_frame = dataframe.copy()
    if search_filter.strip():
        needle = search_filter.strip().lower()
        filtered_frame = filtered_frame[
            filtered_frame["device_name"].str.lower().str.contains(needle, na=False)
            | filtered_frame["summary"].str.lower().str.contains(needle, na=False)
        ]

    if filtered_frame.empty:
        st.info("Tidak ada incident yang cocok dengan filter saat ini.")
        return

    if sort_mode == "Berdasarkan Status":
        filtered_frame = filtered_frame.sort_values(["status_priority", "started_at"], ascending=[True, False])
    elif sort_mode == "Durasi Terpanjang":
        filtered_frame = filtered_frame.sort_values(["duration_minutes", "started_at"], ascending=[False, False])
    else:
        filtered_frame = filtered_frame.sort_values("started_at", ascending=False)

    total_incidents = int(len(filtered_frame))
    active_incidents = int(filtered_frame["status"].str.lower().eq("active").sum())
    resolved_incidents = int(filtered_frame["status"].str.lower().eq("resolved").sum())
    affected_devices = int(filtered_frame["device_name"].nunique())

    duration_series = filtered_frame["duration_minutes"].dropna()
    median_duration_label = _duration_label(duration_series.median() if not duration_series.empty else None)

    render_kpi_cards(
        [
            ("Total Insiden", total_incidents, None),
            ("Insiden Aktif", active_incidents, None),
            ("Insiden Selesai", resolved_incidents, None),
            ("Device Terdampak", affected_devices, None),
            ("Durasi Median", median_duration_label, None),
        ],
        columns_per_row=5,
    )

    status_counts = (
        filtered_frame["status"]
        .value_counts()
        .rename_axis("Status")
        .reset_index(name="Count")
    )
    status_counts["Priority"] = status_counts["Status"].map(status_priority)
    status_counts = status_counts.sort_values(["Priority", "Count", "Status"], ascending=[True, False, True])
    top_devices = (
        filtered_frame["device_name"]
        .value_counts()
        .rename_axis("Device")
        .reset_index(name="Incidents")
        .sort_values("Incidents", ascending=False)
        .head(10)
    )

    summary_col, top_col = st.columns([1, 1])
    with summary_col:
        st.markdown("### Incident Distribution")
        status_chart = (
            alt.Chart(status_counts)
            .mark_bar()
            .encode(
                x=alt.X("Count:Q", title="Incidents"),
                y=alt.Y("Status:N", sort="-x", title="Status"),
                tooltip=[alt.Tooltip("Status:N", title="Status"), alt.Tooltip("Count:Q", title="Count")],
            )
            .properties(height=280)
        )
        st.altair_chart(status_chart, width="stretch")
        st.dataframe(
            status_counts[["Status", "Count"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Count": st.column_config.NumberColumn("Count", width="small", format="%d"),
            },
        )
    with top_col:
        st.markdown("### Device Paling Terdampak")
        device_chart = (
            alt.Chart(top_devices)
            .mark_bar()
            .encode(
                x=alt.X("Incidents:Q", title="Incidents"),
                y=alt.Y("Device:N", sort="-x", title="Device"),
                tooltip=[alt.Tooltip("Device:N", title="Device"), alt.Tooltip("Incidents:Q", title="Incidents")],
            )
            .properties(height=280)
        )
        st.altair_chart(device_chart, width="stretch")
        st.dataframe(
            top_devices,
            width="stretch",
            hide_index=True,
            column_config={
                "Device": st.column_config.TextColumn("Device", width="large"),
                "Incidents": st.column_config.NumberColumn("Incidents", width="small", format="%d"),
            },
        )

    detail_columns = ["started_at_wib", "ended_at_wib", "duration_label", "device_name", "status", "summary"]
    detail_frame = filtered_frame[detail_columns].rename(
        columns={
            "started_at_wib": "Started At (WIB)",
            "ended_at_wib": "Ended At (WIB)",
            "duration_label": "Duration",
            "device_name": "Device",
            "status": "Status",
            "summary": "Summary",
        }
    )
    st.markdown("### Detail Insiden")
    st.dataframe(
        detail_frame.head(int(max_rows)),
        width="stretch",
        hide_index=True,
        column_config={
            "Started At (WIB)": st.column_config.TextColumn("Started At (WIB)", width="medium"),
            "Ended At (WIB)": st.column_config.TextColumn("Ended At (WIB)", width="medium"),
            "Duration": st.column_config.TextColumn("Duration", width="small"),
            "Device": st.column_config.TextColumn("Device", width="medium"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Summary": st.column_config.TextColumn("Summary", width="large"),
        },
    )


render_live_section(auto_refresh, interval_seconds, _render_incidents_body)
