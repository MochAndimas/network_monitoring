"""Define module logic for `dashboard/pages/6_Incidents.py`.

This module contains project-specific implementation details.
"""

from html import escape
from urllib.parse import quote_plus

import altair as alt
import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json, paged_items, paged_meta
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp
from components.ui import normalize_status_label, render_kpi_cards, render_meta_row, render_page_header, status_priority

st.set_page_config(page_title="Incidents", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "Incidents",
    "Pelacakan insiden aktif dan selesai untuk evaluasi dampak operasional.",
)

filter_col1, filter_col2 = st.columns([1, 2])
status_filter = filter_col1.selectbox(
    "Status Insiden",
    options=["All", "active", "resolved"],
    index=0,
    format_func=lambda value: "Semua" if value == "All" else normalize_status_label(str(value)),
)
search_filter = filter_col2.text_input("Cari", placeholder="Filter berdasarkan device atau ringkasan")
with st.expander("Filter Lanjutan"):
    adv_col1, adv_col2, adv_col3 = st.columns(3)
    sort_mode = adv_col1.selectbox("Urutkan", options=["Terbaru", "Durasi Terpanjang", "Berdasarkan Status"], index=0)
    max_rows = adv_col2.selectbox("Maks. Baris Detail", options=[25, 50, 100, 200], index=1)
    incidents_page_size = adv_col3.selectbox("Baris per Halaman", options=[25, 50, 100, 200], index=1)
auto_refresh, interval_seconds = refresh_controls("incidents", default_enabled=True, default_interval=15)
incidents_page_key = "incidents_page"
incidents_filter_signature_key = "incidents_filter_signature"
incidents_filter_signature = (
    str(status_filter),
    search_filter.strip().lower(),
    str(sort_mode),
    int(incidents_page_size),
)
if st.session_state.get(incidents_filter_signature_key) != incidents_filter_signature:
    st.session_state[incidents_page_key] = 1
    st.session_state[incidents_filter_signature_key] = incidents_filter_signature
current_incidents_page = max(int(st.session_state.get(incidents_page_key, 1) or 1), 1)
incidents_offset = (current_incidents_page - 1) * int(incidents_page_size)


def _duration_label(minutes_value: float | None) -> str:
    """Perform duration label.

    Args:
        minutes_value: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    if minutes_value is None or pd.isna(minutes_value):
        return "-"
    minutes = int(minutes_value)
    hours, mins = divmod(minutes, 60)
    return f"{hours}j {mins}m" if hours else f"{mins}m"


def _render_detail_table(dataframe: pd.DataFrame) -> None:
    """Render incident detail table with wrapped summary text."""
    headers = list(dataframe.columns)
    header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    rows_html = []
    for _, row in dataframe.iterrows():
        cells = []
        for header in headers:
            raw_value = "" if pd.isna(row[header]) else str(row[header])
            cell_value = escape(raw_value)
            cell_class = "summary-cell" if header == "Ringkasan" else ""
            if header == "Ringkasan":
                cell_value = cell_value.replace("; ", "<br>")
            cells.append(f'<td class="{cell_class}">{cell_value}</td>')
        rows_html.append(f"<tr>{''.join(cells)}</tr>")

    st.markdown(
        f"""
        <style>
        .incident-detail-table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 0.95rem;
        }}
        .incident-detail-table th {{
            color: #a7b0bf;
            background: #171a22;
            border: 1px solid #2a2f3a;
            padding: 0.72rem 0.7rem;
            text-align: left;
            font-weight: 600;
        }}
        .incident-detail-table td {{
            border: 1px solid #252a34;
            padding: 0.72rem 0.7rem;
            vertical-align: top;
            overflow-wrap: anywhere;
            word-break: normal;
        }}
        .incident-detail-table th:nth-child(1),
        .incident-detail-table th:nth-child(2) {{
            width: 16%;
        }}
        .incident-detail-table th:nth-child(3) {{
            width: 6%;
        }}
        .incident-detail-table th:nth-child(4) {{
            width: 16%;
        }}
        .incident-detail-table th:nth-child(5) {{
            width: 8%;
        }}
        .incident-detail-table th:nth-child(6) {{
            width: 38%;
        }}
        .incident-detail-table .summary-cell {{
            line-height: 1.45;
            white-space: normal;
        }}
        @media (max-width: 900px) {{
            .incident-detail-table {{
                font-size: 0.85rem;
            }}
            .incident-detail-table th,
            .incident-detail-table td {{
                padding: 0.55rem 0.5rem;
            }}
        }}
        </style>
        <div style="overflow-x:auto;">
            <table class="incident-detail-table">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{''.join(rows_html)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_incidents_body() -> None:
    """Render incidents body.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    path = f"/incidents/paged?limit={int(incidents_page_size)}&offset={incidents_offset}"
    if status_filter != "All":
        path = f"{path}&status={status_filter}"
    normalized_search_filter = search_filter.strip()
    if normalized_search_filter:
        path = f"{path}&search={quote_plus(normalized_search_filter)}"
    incidents_payload = get_json(
        path,
        {"items": [], "meta": {"total": 0, "limit": int(incidents_page_size), "offset": incidents_offset}},
    )
    incidents = paged_items(incidents_payload, [])
    incidents_meta = paged_meta(incidents_payload)
    incidents_total = int(incidents_meta.get("total") or 0)
    incidents_total_pages = max((incidents_total - 1) // int(incidents_page_size) + 1, 1)
    if current_incidents_page > incidents_total_pages:
        st.session_state[incidents_page_key] = incidents_total_pages
        st.rerun()
    start_row = 0 if incidents_total == 0 else incidents_offset + 1
    end_row = min(incidents_offset + len(incidents), incidents_total)

    render_meta_row(
        [
            ("Refresh Otomatis", live_status_text(auto_refresh, interval_seconds)),
            ("Terakhir Diperbarui", rendered_at_label()),
            ("Filter Status", normalize_status_label(status_filter)),
            ("Urutan", sort_mode),
            ("Cakupan Data", f"{start_row}-{end_row} / {incidents_total} incidents"),
        ]
    )
    page_col, page_meta_col = st.columns([1, 4])
    page_col.number_input(
        "Halaman Incidents",
        min_value=1,
        max_value=incidents_total_pages,
        value=min(current_incidents_page, incidents_total_pages),
        step=1,
        key=incidents_page_key,
    )
    page_meta_col.caption(f"Menampilkan {start_row}-{end_row} dari {incidents_total} incidents.")

    if not incidents:
        st.info("Belum ada insiden tercatat. Data akan muncul setelah gangguan terdeteksi.")
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

    if filtered_frame.empty:
        st.info("Tidak ada insiden yang cocok dengan filter. Coba ubah kata kunci pencarian.")
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
        .reset_index(name="Jumlah")
    )
    status_counts["Priority"] = status_counts["Status"].map(status_priority)
    status_counts = status_counts.sort_values(["Priority", "Jumlah", "Status"], ascending=[True, False, True])
    top_devices = (
        filtered_frame["device_name"]
        .value_counts()
        .rename_axis("Nama Device")
        .reset_index(name="Jumlah Insiden")
        .sort_values("Jumlah Insiden", ascending=False)
        .head(10)
    )

    summary_col, top_col = st.columns([1, 1])
    with summary_col:
        st.markdown("### Distribusi Status Insiden")
        status_chart = (
            alt.Chart(status_counts)
            .mark_bar()
            .encode(
                x=alt.X("Jumlah:Q", title="Jumlah Insiden"),
                y=alt.Y("Status:N", sort="-x", title="Status"),
                tooltip=[alt.Tooltip("Status:N", title="Status"), alt.Tooltip("Jumlah:Q", title="Jumlah")],
            )
            .properties(height=260)
        )
        st.altair_chart(status_chart, width="stretch")
        st.dataframe(
            status_counts[["Status", "Jumlah"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
            },
        )
    with top_col:
        st.markdown("### Device Paling Terdampak")
        device_chart = (
            alt.Chart(top_devices)
            .mark_bar()
            .encode(
                x=alt.X("Jumlah Insiden:Q", title="Jumlah Insiden"),
                y=alt.Y("Nama Device:N", sort="-x", title="Nama Device"),
                tooltip=[alt.Tooltip("Nama Device:N", title="Nama Device"), alt.Tooltip("Jumlah Insiden:Q", title="Jumlah")],
            )
            .properties(height=260)
        )
        st.altair_chart(device_chart, width="stretch")
        st.dataframe(
            top_devices,
            width="stretch",
            hide_index=True,
            column_config={
                "Nama Device": st.column_config.TextColumn("Nama Device", width="large"),
                "Jumlah Insiden": st.column_config.NumberColumn("Jumlah Insiden", width="small", format="%d"),
            },
        )

    detail_columns = ["started_at_wib", "ended_at_wib", "duration_label", "device_name", "status", "summary"]
    detail_frame = filtered_frame[detail_columns].rename(
        columns={
            "started_at_wib": "Mulai (WIB)",
            "ended_at_wib": "Selesai (WIB)",
            "duration_label": "Durasi",
            "device_name": "Nama Device",
            "status": "Status",
            "summary": "Ringkasan",
        }
    )
    st.markdown("### Detail Insiden")
    _render_detail_table(detail_frame.head(int(max_rows)))
    st.markdown("")
    st.caption("Tip: gunakan urutan Durasi Terpanjang untuk meninjau insiden dengan dampak waktu terbesar.")


render_live_section(auto_refresh, interval_seconds, _render_incidents_body)
