"""Define module logic for `dashboard/pages/2_Daily_Summary.py`.

This module contains project-specific implementation details.
"""

from datetime import datetime, timedelta
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import streamlit as st

from shared.device_utils import format_device_label
from components.auth import require_dashboard_login
from components.api import get_json, get_json_map, paged_items, paged_meta
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp
from components.ui import render_kpi_cards, render_meta_row, render_page_header


st.set_page_config(page_title="Daily Summary", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "Daily Summary",
    "Ringkasan harian dari data rollup untuk analisis tren tanpa membaca raw history.",
)


def _format_number(value, suffix: str = "", decimals: int = 2) -> str:
    """Format number.

    Args:
        value: Parameter input untuk routine ini.
        suffix: Parameter input untuk routine ini.
        decimals: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{decimals}f}{suffix}"


def _prepare_summary_frame(rows: list[dict]) -> pd.DataFrame:
    """Perform prepare summary frame.

    Args:
        rows: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        return dataframe
    dataframe["rollup_date"] = pd.to_datetime(dataframe["rollup_date"])
    dataframe["Tanggal"] = dataframe["rollup_date"].dt.strftime("%Y-%m-%d")
    dataframe["Device"] = dataframe["device_name"].fillna("Unknown Device")
    dataframe["Tipe"] = dataframe["device_type"].fillna("-")
    dataframe["Sampel"] = dataframe["total_samples"].fillna(0).astype(int)
    dataframe["Ping Sampel"] = dataframe["ping_samples"].fillna(0).astype(int)
    dataframe["Down"] = dataframe["down_count"].fillna(0).astype(int)
    dataframe["Uptime"] = dataframe["uptime_percentage"].apply(lambda value: _format_number(value, "%"))
    dataframe["Avg Ping"] = dataframe["average_ping_ms"].apply(lambda value: _format_number(value, " ms"))
    dataframe["Min Ping"] = dataframe["min_ping_ms"].apply(lambda value: _format_number(value, " ms"))
    dataframe["Max Ping"] = dataframe["max_ping_ms"].apply(lambda value: _format_number(value, " ms"))
    dataframe["Packet Loss"] = dataframe["average_packet_loss_percent"].apply(lambda value: _format_number(value, "%"))
    dataframe["Avg Jitter"] = dataframe["average_jitter_ms"].apply(lambda value: _format_number(value, " ms"))
    dataframe["Max Jitter"] = dataframe["max_jitter_ms"].apply(lambda value: _format_number(value, " ms"))
    dataframe["updated_at"] = to_wib_timestamp(dataframe["updated_at"])
    dataframe["Terakhir Update"] = dataframe["updated_at"].apply(format_wib_timestamp)
    return dataframe


def _weighted_average(dataframe: pd.DataFrame, value_column: str, weight_column: str) -> float | None:
    """Perform weighted average.

    Args:
        dataframe: Parameter input untuk routine ini.
        value_column: Parameter input untuk routine ini.
        weight_column: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if dataframe.empty or value_column not in dataframe.columns or weight_column not in dataframe.columns:
        return None
    working = dataframe[[value_column, weight_column]].dropna().copy()
    if working.empty:
        return None
    weights = pd.to_numeric(working[weight_column], errors="coerce").fillna(0)
    values = pd.to_numeric(working[value_column], errors="coerce")
    total_weight = float(weights.sum())
    if total_weight <= 0 or values.isna().all():
        return None
    return float((values.fillna(0) * weights).sum() / total_weight)


def _weighted_average_for_group(group: pd.DataFrame, value_column: str, weight_column: str) -> float | None:
    """Perform weighted average for group.

    Args:
        group: Parameter input untuk routine ini.
        value_column: Parameter input untuk routine ini.
        weight_column: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return _weighted_average(group, value_column, weight_column)


def _aggregate_all_devices_weighted(frame: pd.DataFrame) -> pd.DataFrame:
    """Perform aggregate all devices weighted.

    Args:
        frame: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    rows: list[dict] = []
    for rollup_date, group in frame.groupby("rollup_date"):
        rows.append(
            {
                "rollup_date": rollup_date,
                "ping_samples": int(group["ping_samples"].fillna(0).sum()),
                "total_samples": int(group["total_samples"].fillna(0).sum()),
                "down_count": int(group["down_count"].fillna(0).sum()),
                "uptime_percentage": _weighted_average_for_group(group, "uptime_percentage", "ping_samples"),
                "average_ping_ms": _weighted_average_for_group(group, "average_ping_ms", "ping_samples"),
                "average_packet_loss_percent": _weighted_average_for_group(
                    group, "average_packet_loss_percent", "ping_samples"
                ),
                "average_jitter_ms": _weighted_average_for_group(group, "average_jitter_ms", "ping_samples"),
                "max_ping_ms": pd.to_numeric(group["max_ping_ms"], errors="coerce").max(),
                "Device": "Semua Device",
            }
        )
    if not rows:
        return pd.DataFrame(columns=["rollup_date", "Device"])
    return pd.DataFrame(rows).sort_values("rollup_date").reset_index(drop=True)


payload = get_json_map(
    {
        "devices": ("/devices/options?active_only=false&limit=1000&offset=0", []),
    }
)
devices = list(payload.get("devices", []))
device_options = {"Semua Device": None}
for device in devices:
    device_options[format_device_label(device)] = device["id"]

today = datetime.now().date()
default_start_date = today - timedelta(days=7)

filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 1])
selected_device = filter_col1.selectbox("Device", options=list(device_options.keys()))
date_range = filter_col2.date_input(
    "Rentang Tanggal",
    value=(default_start_date, today),
)
if isinstance(date_range, tuple):
    date_from, date_to = date_range
else:
    date_from = date_range
    date_to = date_range
limit_value = filter_col3.selectbox("Baris", options=[50, 100, 200, 500], index=1)
page_key = "daily_summary_page"
current_page = max(int(st.session_state.get(page_key, 1) or 1), 1)
offset_value = (current_page - 1) * int(limit_value)

query_params: dict[str, object] = {
    "limit": limit_value,
    "offset": offset_value,
}
selected_device_id = device_options[selected_device]
if selected_device_id is not None:
    query_params["device_id"] = selected_device_id
if date_from:
    query_params["rollup_from"] = date_from.isoformat()
if date_to:
    query_params["rollup_to"] = date_to.isoformat()

summary_payload = get_json(
    f"/metrics/daily-summary?{urlencode(query_params)}",
    {"items": [], "meta": {"total": 0, "limit": limit_value, "offset": 0}},
)
summary_rows = paged_items(summary_payload)
summary_meta = paged_meta(summary_payload)
summary_total = int(summary_meta.get("total", 0) or 0)
summary_total_pages = max((summary_total - 1) // int(limit_value) + 1, 1)
if current_page > summary_total_pages:
    st.session_state[page_key] = summary_total_pages
    st.rerun()

render_meta_row(
    [
        ("Sumber Data", "metrics_daily_rollups"),
        ("Device", selected_device),
        ("Rentang", f"{date_from} s/d {date_to}"),
        ("Total Rollup", summary_total),
    ]
)
page_col, page_meta_col = st.columns([1, 4])
page_col.number_input(
    "Halaman Summary",
    min_value=1,
    max_value=summary_total_pages,
    value=min(current_page, summary_total_pages),
    step=1,
    key=page_key,
)
start_row = 0 if summary_total == 0 else offset_value + 1
end_row = min(offset_value + len(summary_rows), summary_total)
page_meta_col.caption(f"Menampilkan {start_row}-{end_row} dari {summary_total} rollup.")

summary_frame = _prepare_summary_frame(summary_rows)
if summary_frame.empty:
    st.info("Belum ada data rollup harian untuk filter ini. Rollup dibuat oleh proses retention/cleanup harian.")
    st.stop()

total_samples = int(summary_frame["total_samples"].fillna(0).sum())
total_down = int(summary_frame["down_count"].fillna(0).sum())
weighted_uptime = _weighted_average(summary_frame, "uptime_percentage", "ping_samples")
weighted_ping = _weighted_average(summary_frame, "average_ping_ms", "ping_samples")
weighted_loss = _weighted_average(summary_frame, "average_packet_loss_percent", "ping_samples")
max_jitter = summary_frame["max_jitter_ms"].dropna().max() if "max_jitter_ms" in summary_frame else None

render_kpi_cards(
    [
        ("Total Sampel", total_samples, None),
        ("Total Down", total_down, None),
        ("Uptime Rata-rata", _format_number(weighted_uptime, "%"), None),
        ("Avg Ping", _format_number(weighted_ping, " ms"), None),
        ("Packet Loss", _format_number(weighted_loss, "%"), None),
        ("Max Jitter", _format_number(max_jitter, " ms"), None),
    ],
    columns_per_row=6,
)

chart_frame = summary_frame.sort_values("rollup_date").copy()
if selected_device_id is None:
    chart_frame = _aggregate_all_devices_weighted(chart_frame)

chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    st.markdown("### Uptime Harian")
    uptime_chart = (
        alt.Chart(chart_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("rollup_date:T", title="Tanggal"),
            y=alt.Y("uptime_percentage:Q", title="Uptime (%)"),
            color=alt.Color("Device:N", title="Device"),
            tooltip=[
                alt.Tooltip("rollup_date:T", title="Tanggal", format="%Y-%m-%d"),
                alt.Tooltip("Device:N", title="Device"),
                alt.Tooltip("uptime_percentage:Q", title="Uptime", format=".2f"),
                alt.Tooltip("down_count:Q", title="Down"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(uptime_chart, width="stretch")

with chart_col2:
    st.markdown("### Ping Harian")
    ping_chart = (
        alt.Chart(chart_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("rollup_date:T", title="Tanggal"),
            y=alt.Y("average_ping_ms:Q", title="Avg Ping (ms)"),
            color=alt.Color("Device:N", title="Device"),
            tooltip=[
                alt.Tooltip("rollup_date:T", title="Tanggal", format="%Y-%m-%d"),
                alt.Tooltip("Device:N", title="Device"),
                alt.Tooltip("average_ping_ms:Q", title="Avg Ping", format=".2f"),
                alt.Tooltip("max_ping_ms:Q", title="Max Ping", format=".2f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(ping_chart, width="stretch")

st.markdown("### Detail Rollup")
detail_columns = [
    "Tanggal",
    "Device",
    "Tipe",
    "Sampel",
    "Ping Sampel",
    "Down",
    "Uptime",
    "Avg Ping",
    "Min Ping",
    "Max Ping",
    "Packet Loss",
    "Avg Jitter",
    "Max Jitter",
    "Terakhir Update",
]
st.dataframe(
    summary_frame[detail_columns],
    width="stretch",
    hide_index=True,
    column_config={
        "Tanggal": st.column_config.TextColumn("Tanggal", width="small"),
        "Device": st.column_config.TextColumn("Device", width="medium"),
        "Tipe": st.column_config.TextColumn("Tipe", width="small"),
        "Terakhir Update": st.column_config.TextColumn("Terakhir Update", width="medium"),
    },
)
