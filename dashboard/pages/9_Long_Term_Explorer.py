"""Streamlit dashboard page for long-term metric archive exploration."""

from datetime import date, timedelta
from urllib.parse import quote_plus

import altair as alt
import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json, paged_items, paged_meta
from components.sidebar import collapse_sidebar_on_page_load
from components.ui import render_kpi_cards, render_page_header, render_section_header_with_download


st.set_page_config(page_title="Long-Term Explorer", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "Long-Term Explorer",
    "Eksplorasi tren historis dari rollup dan cold archive tanpa query raw metrics besar.",
)

default_to = date.today()
default_from = default_to - timedelta(days=90)
filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
archive_from = filter_col1.date_input("Dari", value=default_from)
archive_to = filter_col2.date_input("Sampai", value=default_to)
metric_name = filter_col3.text_input("Metric", placeholder="Contoh: ping")
site = filter_col4.text_input("Site", placeholder="Kosongkan untuk semua")

adv_col1, adv_col2, adv_col3 = st.columns(3)
device_type = adv_col1.text_input("Device Type", placeholder="Contoh: mikrotik")
limit = adv_col2.selectbox("Rows Archive", options=[50, 100, 200, 500], index=1)
offset = adv_col3.number_input("Offset Archive", min_value=0, value=0, step=int(limit))

query_parts = [
    f"limit={int(limit)}",
    f"offset={int(offset)}",
    f"archive_from={archive_from.isoformat()}",
    f"archive_to={archive_to.isoformat()}",
]
if metric_name.strip():
    query_parts.append(f"metric_name={quote_plus(metric_name.strip())}")
if site.strip():
    query_parts.append(f"site={quote_plus(site.strip())}")
if device_type.strip():
    query_parts.append(f"device_type={quote_plus(device_type.strip())}")

payload = get_json(
    f"/metrics/long-term-explorer?{'&'.join(query_parts)}",
    {"trends": [], "archives": {"items": [], "meta": {"total": 0, "limit": int(limit), "offset": int(offset)}}},
)
trends = payload.get("trends", []) if isinstance(payload, dict) else []
archive_payload = payload.get("archives", {}) if isinstance(payload, dict) else {}
archives = paged_items(archive_payload, [])
archive_meta = paged_meta(archive_payload)

trend_frame = pd.DataFrame(trends)
archive_frame = pd.DataFrame(archives)

render_kpi_cards(
    [
        ("Trend Rows", int(len(trend_frame)), None),
        ("Archive Rows", int(len(archive_frame)), None),
        ("Archive Total", int(archive_meta.get("total") or 0), None),
        ("Source", "rollup/archive", None),
    ],
    columns_per_row=4,
)

if trend_frame.empty:
    st.info("Belum ada materialized long-term trend untuk filter ini. Data dibuat oleh retention cleanup.")
else:
    trend_frame["summary_date"] = pd.to_datetime(trend_frame["summary_date"], errors="coerce")
    render_section_header_with_download(
        "Trend Site / Device Type",
        trend_frame,
        file_name="long_term_trends.csv",
        key="download_long_term_trends",
    )
    metric_choice = st.selectbox(
        "Trend Metric",
        options=[
            "average_uptime_percentage",
            "average_ping_ms",
            "average_packet_loss_percent",
            "average_jitter_ms",
            "max_jitter_ms",
        ],
        index=0,
    )
    chart = (
        alt.Chart(trend_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("summary_date:T", title="Tanggal"),
            y=alt.Y(f"{metric_choice}:Q", title=metric_choice),
            color=alt.Color("site:N", title="Site"),
            strokeDash=alt.StrokeDash("device_type:N", title="Type"),
            tooltip=["summary_date:T", "site:N", "device_type:N", alt.Tooltip(f"{metric_choice}:Q", format=".2f")],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(trend_frame, width="stretch", hide_index=True)

if archive_frame.empty:
    st.info("Belum ada cold archive rows untuk filter ini.")
else:
    render_section_header_with_download(
        "Cold Archive Detail",
        archive_frame,
        file_name="cold_archive.csv",
        key="download_cold_archive",
    )
    st.dataframe(
        archive_frame,
        width="stretch",
        hide_index=True,
        column_config={
            "device_name": st.column_config.TextColumn("Device", width="medium"),
            "site": st.column_config.TextColumn("Site", width="small"),
            "device_type": st.column_config.TextColumn("Type", width="small"),
            "metric_name": st.column_config.TextColumn("Metric", width="medium"),
            "avg_numeric_value": st.column_config.NumberColumn("Avg", format="%.3f"),
            "sample_count": st.column_config.NumberColumn("Samples", format="%d"),
        },
    )
