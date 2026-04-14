from datetime import datetime, time, timedelta
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import streamlit as st

from components.api import get_json, paged_items, paged_meta
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp

st.set_page_config(page_title="History", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()


STATUS_OPTIONS = ["All", "up", "down", "ok", "error", "warning"]
CHART_WINDOW_OPTIONS = {
    "1 jam": 1,
    "6 jam": 6,
    "12 jam": 12,
    "24 jam": 24,
    "7 hari": 24 * 7,
}
HISTORY_CSS = """
<style>
.stMainBlockContainer,
[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 100%;
    padding-left: 2rem;
    padding-right: 2rem;
}
.history-meta {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin: 0.3rem 0 1.1rem 0;
}
.history-pill {
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.03);
    border-radius: 999px;
    padding: 0.45rem 0.8rem;
    font-size: 0.9rem;
    color: rgba(250,250,250,0.8);
}
.history-card {
    border: 1px solid rgba(255,255,255,0.08);
    background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02));
    border-radius: 18px;
    padding: 1rem 1rem 0.95rem 1rem;
    min-height: 118px;
    margin-bottom: 0.35rem;
}
.history-card-label {
    font-size: 0.9rem;
    line-height: 1.35;
    color: rgba(250,250,250,0.72);
    margin-bottom: 0.6rem;
}
.history-card-value {
    font-size: clamp(1.35rem, 2vw, 2.5rem);
    line-height: 1.08;
    font-weight: 700;
    color: #f8fafc;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.history-card-value.compact {
    font-size: clamp(1rem, 1.35vw, 1.4rem);
    line-height: 1.25;
}
.history-note {
    border: 1px solid rgba(255,255,255,0.08);
    background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.015));
    border-radius: 18px;
    padding: 1rem 1.1rem;
    margin: 0.25rem 0 1rem 0;
}
.history-note-title {
    font-size: 0.95rem;
    font-weight: 700;
    margin-bottom: 0.35rem;
    color: #f8fafc;
}
.history-note-body {
    font-size: 0.95rem;
    line-height: 1.5;
    color: rgba(250,250,250,0.78);
}
</style>
"""
METRIC_LABELS = {
    "ping": ("Ping Latency", "Waktu respon ping ke device/target."),
    "packet_loss": ("Packet Loss", "Persentase paket ping yang gagal sampai ke target."),
    "jitter": ("Jitter", "Rata-rata perubahan latency antar sample ping."),
    "dns_resolution_time": ("DNS Resolution", "Waktu yang dibutuhkan untuk resolve hostname DNS check."),
    "http_response_time": ("HTTP Response", "Waktu respon HTTP check ke URL yang dikonfigurasi."),
    "public_ip": ("Public IP", "IP public yang terlihat dari jaringan saat monitoring berjalan."),
    "reachability": ("Ping Latency", "Nama lama untuk metric ping latency."),
    "cpu_percent": ("CPU Usage", "Persentase penggunaan CPU."),
    "memory_percent": ("Memory Usage", "Persentase penggunaan RAM/memori."),
    "disk_percent": ("Disk Usage", "Persentase penggunaan disk."),
    "boot_time_epoch": ("Boot Time", "Waktu boot terakhir dalam epoch timestamp."),
    "interfaces_running": ("Active Interfaces", "Jumlah interface Mikrotik yang sedang running."),
    "mikrotik_api": ("Mikrotik API Status", "Status koneksi ke API Mikrotik."),
}


def _format_device_label(device: dict) -> str:
    return f'{device["name"]} ({device["device_type"]})'


def _default_device_option_label(devices: list[dict]) -> str:
    internet_targets = [device for device in devices if device.get("device_type") == "internet_target"]
    if not internet_targets:
        return "All Devices"

    preferred_device = next(
        (device for device in internet_targets if "myrepublic" in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return _format_device_label(preferred_device)

    preferred_device = next(
        (device for device in internet_targets if "isp" in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return _format_device_label(preferred_device)

    preferred_device = next(
        (device for device in internet_targets if "mikrotik" not in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return _format_device_label(preferred_device)
    return "All Devices"


def _format_metric_value(row: pd.Series) -> str:
    unit = f' {row["unit"]}' if row.get("unit") else ""
    return f'{row["metric_value"]}{unit}'


def _friendly_metric_name(metric_name: str) -> str:
    return METRIC_LABELS.get(metric_name, (metric_name.replace("_", " ").title(), ""))[0]


def _metric_description(metric_name: str) -> str:
    return METRIC_LABELS.get(metric_name, ("", "Metric monitoring."))[1]


def _metric_filter_label(metric_name: str) -> str:
    if metric_name == "All Metrics":
        return metric_name
    return f"{_friendly_metric_name(metric_name)} ({metric_name})"


def _y_axis_label(metric_name: str, unit: str | None) -> str:
    friendly_name = _friendly_metric_name(metric_name)
    if unit:
        return f"{friendly_name} ({unit})"
    return friendly_name


def _format_duration(delta: pd.Timedelta | None) -> str:
    if delta is None or pd.isna(delta):
        return "-"
    total_seconds = max(int(delta.total_seconds()), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}j")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}dtk")
    return " ".join(parts)


def _status_rollup(statuses: list[str]) -> str:
    normalized = [str(status).lower() for status in statuses if status]
    if not normalized:
        return "unknown"
    if any(status in {"down", "critical", "error"} for status in normalized):
        return "down"
    if any(status in {"warning", "degraded", "unavailable"} for status in normalized):
        return "warning"
    if all(status in {"up", "healthy", "ok"} for status in normalized):
        return "up"
    return normalized[0]


def _continuous_up_duration(series_frame: pd.DataFrame) -> str:
    if series_frame.empty:
        return "-"
    ordered = series_frame.sort_values("checked_at").copy()
    latest_row = ordered.iloc[-1]
    latest_status = str(latest_row.get("status") or "").lower()
    if latest_status not in {"up", "ok"}:
        return "-"

    consecutive_rows = []
    for _, row in ordered.iloc[::-1].iterrows():
        status = str(row.get("status") or "").lower()
        if status in {"up", "ok"}:
            consecutive_rows.append(row)
            continue
        break

    if not consecutive_rows:
        return "-"

    oldest_consecutive = consecutive_rows[-1]
    duration = latest_row["checked_at"] - oldest_consecutive["checked_at"]
    return _format_duration(duration)


def _prepare_history_frame(history: list[dict], *, sort_desc: bool = True) -> pd.DataFrame:
    dataframe = pd.DataFrame(history)
    if dataframe.empty:
        return dataframe

    dataframe["checked_at"] = to_wib_timestamp(dataframe["checked_at"])
    if sort_desc:
        dataframe = dataframe.sort_values("checked_at", ascending=False).copy()
    else:
        dataframe = dataframe.copy()
    dataframe["metric_label"] = dataframe["metric_name"].map(lambda name: _friendly_metric_name(name))
    dataframe["checked_at_wib"] = dataframe["checked_at"].map(format_wib_timestamp)
    unit_series = dataframe["unit"].fillna("")
    dataframe["display_value"] = dataframe["metric_value"] + unit_series.map(lambda unit: f" {unit}" if unit else "")
    return dataframe


def _fetch_metric_series(
    *,
    device_id: int,
    metric_name: str,
    status: str | None,
    checked_from_date,
    checked_to_date,
) -> list[dict]:
    page_size = 500
    offset = 0
    items: list[dict] = []

    while True:
        query_params = {
            "limit": page_size,
            "offset": offset,
            "device_id": device_id,
            "metric_name": metric_name,
        }
        if status and status != "All":
            query_params["status"] = status
        if checked_from_date:
            query_params["checked_from"] = datetime.combine(checked_from_date, time.min).isoformat()
        if checked_to_date:
            query_params["checked_to"] = datetime.combine(checked_to_date, time.max).isoformat()

        payload = get_json(f"/metrics/history/paged?{urlencode(query_params)}", {"items": [], "meta": {}})
        page_items = paged_items(payload)
        if not page_items:
            break

        items.extend(page_items)
        meta = paged_meta(payload)
        offset += len(page_items)
        total = int(meta.get("total", 0) or 0)
        if offset >= total:
            break

    return items


def _fetch_latest_snapshot_rows() -> list[dict]:
    page_size = 500
    offset = 0
    items: list[dict] = []

    while True:
        payload = get_json(f"/metrics/latest-snapshot/paged?limit={page_size}&offset={offset}", {"items": [], "meta": {}})
        page_items = paged_items(payload)
        if not page_items:
            break

        items.extend(page_items)
        meta = paged_meta(payload)
        offset += len(page_items)
        total = int(meta.get("total", 0) or 0)
        if offset >= total:
            break

    return items


def _fetch_all_history_rows() -> list[dict]:
    page_size = 500
    offset = 0
    items: list[dict] = []

    while True:
        payload = get_json(f"/metrics/history/paged?limit={page_size}&offset={offset}", {"items": [], "meta": {}})
        page_items = paged_items(payload)
        if not page_items:
            break

        items.extend(page_items)
        meta = paged_meta(payload)
        offset += len(page_items)
        total = int(meta.get("total", 0) or 0)
        if offset >= total:
            break

    return items


def _latest_snapshot_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    return dataframe.drop_duplicates(subset=["device_name", "metric_name"]).copy()


def _snapshot_pagination_controls(total_rows: int) -> tuple[int, int]:
    page_size_col, page_col, _ = st.columns([1, 1, 4])
    default_page_size = int(st.session_state.get("history_snapshot_page_size", 10))
    if default_page_size not in [10, 25, 50, 100]:
        default_page_size = 10
    page_size = page_size_col.selectbox(
        "Snapshot Rows",
        options=[10, 25, 50, 100],
        index=[10, 25, 50, 100].index(default_page_size),
        key="history_snapshot_page_size",
    )
    total_pages = max((total_rows - 1) // page_size + 1, 1)
    page_number = page_col.number_input(
        "Snapshot Page",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("history_snapshot_page", 1), total_pages),
        step=1,
        key="history_snapshot_page",
    )
    return int(page_size), int(page_number)


def _render_metric_trend_section(
    metric_frame: pd.DataFrame,
    *,
    chart_window_label: str,
    target_column=None,
) -> None:
    container = target_column if target_column is not None else st
    latest_metric_timestamp = metric_frame["checked_at"].max()
    chart_window_hours = CHART_WINDOW_OPTIONS[chart_window_label]
    chart_window_start = latest_metric_timestamp - pd.Timedelta(hours=chart_window_hours)
    chart_metric_frame = metric_frame[metric_frame["checked_at"] >= chart_window_start].copy()
    if chart_metric_frame.empty:
        chart_metric_frame = metric_frame.copy()

    latest_metric_row = chart_metric_frame.iloc[-1]
    metric_unit = latest_metric_row["unit"]
    metric_name = latest_metric_row["metric_name"]
    metric_device_name = latest_metric_row["device_name"]
    metric_label = _friendly_metric_name(metric_name)
    metric_description = _metric_description(metric_name)
    chart_min = float(chart_metric_frame["metric_value_numeric"].min())
    chart_max = float(chart_metric_frame["metric_value_numeric"].max())
    chart_avg = float(chart_metric_frame["metric_value_numeric"].mean())

    unit_suffix = f" ({metric_unit})" if metric_unit else ""
    container.markdown(f"#### {metric_label} - {metric_device_name}")
    container.caption(
        f"Latest {_format_metric_value(latest_metric_row)} | "
        f"Status {str(latest_metric_row['status']).upper()} | "
        f"Window {chart_window_label}{unit_suffix}"
    )

    chart_title = f"{metric_label} Trend - {metric_device_name}"
    rules_frame = pd.DataFrame(
        [
            {"line_label": "Min", "line_value": chart_min},
            {"line_label": "Avg", "line_value": chart_avg},
            {"line_label": "Max", "line_value": chart_max},
        ]
    )
    line_chart = (
        alt.Chart(chart_metric_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "checked_at:T",
                title="Waktu Check (WIB)",
                axis=alt.Axis(format="%H:%M", labelAngle=0),
            ),
            y=alt.Y(
                "metric_value_numeric:Q",
                title=_y_axis_label(metric_name, metric_unit),
            ),
            tooltip=[
                alt.Tooltip("checked_at_wib:N", title="Checked At"),
                alt.Tooltip("device_name:N", title="Device"),
                alt.Tooltip("metric_label:N", title="Metric"),
                alt.Tooltip("display_value:N", title="Value"),
                alt.Tooltip("status:N", title="Status"),
            ],
        )
    )
    reference_lines = (
        alt.Chart(rules_frame)
        .mark_rule(strokeDash=[6, 4], strokeWidth=1.5)
        .encode(
            y=alt.Y("line_value:Q"),
            color=alt.Color(
                "line_label:N",
                title="Reference",
                scale=alt.Scale(
                    domain=["Min", "Avg", "Max"],
                    range=["#f59e0b", "#22c55e", "#ef4444"],
                ),
            ),
            tooltip=[
                alt.Tooltip("line_label:N", title="Line"),
                alt.Tooltip("line_value:Q", title="Value", format=".2f"),
            ],
        )
    )
    chart = (line_chart + reference_lines).properties(title=chart_title, height=280)
    container.altair_chart(chart, width="stretch")


def _build_uptime_map(dataframe: pd.DataFrame) -> dict[tuple[str, str], str]:
    uptime_map: dict[tuple[str, str], str] = {}
    for (device_name, metric_name), series_frame in dataframe.groupby(["device_name", "metric_name"], sort=False):
        uptime_map[(device_name, metric_name)] = _continuous_up_duration(
            series_frame.sort_values("checked_at", ascending=True)
        )
    return uptime_map


def _render_stat_card(column, label: str, value: str | int, *, compact: bool = False) -> None:
    value_class = "history-card-value compact" if compact else "history-card-value"
    column.markdown(
        f"""
        <div class="history-card">
            <div class="history-card-label">{label}</div>
            <div class="{value_class}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(HISTORY_CSS, unsafe_allow_html=True)
st.title("History")
st.caption("Halaman ini menampilkan histori pengecekan metric. Pilih device dan metric supaya grafik lebih jelas dibaca.")

devices_payload = get_json("/devices/paged?active_only=false&limit=1000&offset=0", {"items": [], "meta": {}})
devices = paged_items(devices_payload)
device_options = {"All Devices": None}
for device in devices:
    device_options[_format_device_label(device)] = device["id"]

today = datetime.now().date()
default_start_date = today - timedelta(days=7)
auto_refresh, interval_seconds = refresh_controls("history", default_enabled=True, default_interval=15)


def _render_history_body() -> None:
    meta_container = st.container()
    summary_container = st.container()
    snapshot_container = st.container()
    status_container = st.container()

    default_device_label = _default_device_option_label(devices)
    if "history_selected_device" not in st.session_state:
        st.session_state["history_selected_device"] = default_device_label
    device_option_labels = list(device_options.keys())
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    selected_device = filter_col1.selectbox(
        "Device",
        options=device_option_labels,
        index=device_option_labels.index(default_device_label),
        key="history_selected_device",
    )
    selected_device_id = device_options[selected_device]
    metric_option_params = {}
    if selected_device_id is not None:
        metric_option_params["device_id"] = selected_device_id
    metric_option_query = f"?{urlencode(metric_option_params)}" if metric_option_params else ""
    metric_name_options = get_json(f"/metrics/names{metric_option_query}", [])
    metric_select_options = ["All Metrics"] + metric_name_options
    selected_metric = filter_col2.selectbox(
        "Metric Name",
        options=metric_select_options,
        index=0,
        format_func=_metric_filter_label,
        help="Daftar metric yang sudah tersimpan di history.",
        key="history_selected_metric",
    )
    status_value = filter_col3.selectbox("Status", options=STATUS_OPTIONS, index=0)
    limit_value = filter_col4.selectbox("Rows", options=[50, 100, 200, 300, 500], index=2)
    chart_window_label = st.selectbox(
        "Chart Window",
        options=list(CHART_WINDOW_OPTIONS.keys()),
        index=2,
        help="Pilih rentang waktu yang dipakai untuk chart trend.",
    )
    date_filter_col1, date_filter_col2 = st.columns(2)
    checked_from_date = date_filter_col1.date_input("Checked From", value=default_start_date)
    checked_to_date = date_filter_col2.date_input("Checked To", value=today)

    query_params = {"limit": limit_value}
    if selected_device_id is not None:
        query_params["device_id"] = selected_device_id
    if selected_metric != "All Metrics":
        query_params["metric_name"] = selected_metric
    if status_value != "All":
        query_params["status"] = status_value
    if checked_from_date:
        query_params["checked_from"] = datetime.combine(checked_from_date, time.min).isoformat()
    if checked_to_date:
        query_params["checked_to"] = datetime.combine(checked_to_date, time.max).isoformat()

    history_payload = get_json(f"/metrics/history/paged?{urlencode(query_params)}", {"items": [], "meta": {}})
    history = paged_items(history_payload)
    history_meta = paged_meta(history_payload)
    snapshot_page_size = int(st.session_state.get("history_snapshot_page_size", 10))
    snapshot_page = int(st.session_state.get("history_snapshot_page", 1))
    snapshot_offset = (snapshot_page - 1) * snapshot_page_size
    snapshot_payload = get_json(
        f"/metrics/latest-snapshot/paged?limit={snapshot_page_size}&offset={snapshot_offset}",
        {"items": [], "meta": {}},
    )
    snapshot_history = paged_items(snapshot_payload)
    snapshot_meta = paged_meta(snapshot_payload)
    st.session_state["history_snapshot_total"] = int(snapshot_meta.get("total", 0) or 0)
    snapshot_all_history = _fetch_latest_snapshot_rows()
    all_history = _fetch_all_history_rows()
    with meta_container:
        st.markdown(
            f"""
            <div class="history-meta">
                <div class="history-pill">{live_status_text(auto_refresh, interval_seconds)}</div>
                <div class="history-pill">Render terakhir: {rendered_at_label()}</div>
                <div class="history-pill">Filter aktif: {selected_device}</div>
                <div class="history-pill">Rentang: {checked_from_date} s/d {checked_to_date}</div>
                <div class="history-pill">Window chart: {chart_window_label}</div>
                <div class="history-pill">Total match: {history_meta.get("total", 0)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if not history:
        st.info("Belum ada histori metric yang tersimpan untuk filter ini.")
        return

    dataframe = _prepare_history_frame(history)
    if dataframe.empty:
        st.info("Belum ada histori metric yang tersimpan untuk filter ini.")
        return

    latest_timestamp = dataframe["checked_at"].max()
    snapshot_frame = _prepare_history_frame(snapshot_history, sort_desc=False)
    latest_per_series = snapshot_frame if not snapshot_frame.empty else _latest_snapshot_frame(dataframe)
    latest_per_series_full = _prepare_history_frame(snapshot_all_history, sort_desc=False)
    if latest_per_series_full.empty:
        latest_per_series_full = latest_per_series.copy()
    uptime_source_frame = _prepare_history_frame(all_history)
    if uptime_source_frame.empty:
        uptime_source_frame = dataframe.copy()
    uptime_map = _build_uptime_map(uptime_source_frame)
    latest_per_series["uptime"] = latest_per_series.apply(
        lambda row: uptime_map.get((row["device_name"], row["metric_name"]), "-"),
        axis=1,
    )
    latest_per_series_full["uptime"] = latest_per_series_full.apply(
        lambda row: uptime_map.get((row["device_name"], row["metric_name"]), "-"),
        axis=1,
    )
    latest_per_device = (
        latest_per_series_full.groupby("device_name", as_index=False)["status"]
        .agg(lambda series: _status_rollup(series.tolist()))
        .copy()
    )

    with summary_container:
        summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
        _render_stat_card(summary_col1, "Rows Loaded", int(len(dataframe)))
        _render_stat_card(summary_col2, "Total Match", int(history_meta.get("total", len(dataframe))))
        _render_stat_card(summary_col3, "Latest Check", format_wib_timestamp(latest_timestamp), compact=True)
        _render_stat_card(summary_col4, "Distinct Metrics", int(dataframe["metric_name"].nunique()))

    with snapshot_container:
        st.markdown("### Latest Snapshot")
        st.caption(
            f"Menampilkan {len(latest_per_series)} dari total {snapshot_meta.get('total', len(latest_per_series_full))} snapshot terbaru."
        )
        snapshot_view = latest_per_series[
            ["device_name", "metric_label", "display_value", "uptime", "status", "checked_at_wib"]
        ].rename(
            columns={
                "device_name": "Device",
                "metric_label": "Metric",
                "display_value": "Latest Value",
                "uptime": "Uptime",
                "status": "Status",
                "checked_at_wib": "Checked At (WIB)",
            }
        )
        st.dataframe(snapshot_view, width="stretch")
        _snapshot_pagination_controls(int(snapshot_meta.get("total", len(latest_per_series_full))))

    with status_container:
        st.markdown("### Status Summary")
        status_counts = latest_per_device["status"].fillna("unknown").value_counts().rename_axis("status").reset_index(name="count")
        status_left, status_right = st.columns([1, 2])
        status_left.dataframe(status_counts, width="stretch", hide_index=True)
        status_right.bar_chart(status_counts.set_index("status"))

    st.markdown("### Metric Trend")
    if selected_device_id is None:
        st.info("Pilih satu device dari filter di atas supaya chart trend bisa ditampilkan.")
        return

    numeric_frame = dataframe.dropna(subset=["metric_value_numeric"]).copy()
    if numeric_frame.empty:
        st.info("Tidak ada metric numerik pada filter ini, jadi grafik trend belum bisa ditampilkan.")
        return

    metric_names_to_render = [selected_metric] if selected_metric != "All Metrics" else sorted(
        numeric_frame["metric_name"].dropna().unique().tolist()
    )
    rendered_metric_frames: list[pd.DataFrame] = []
    for metric_name in metric_names_to_render:
        metric_series_history = _fetch_metric_series(
            device_id=int(selected_device_id),
            metric_name=str(metric_name),
            status=status_value,
            checked_from_date=checked_from_date,
            checked_to_date=checked_to_date,
        )
        metric_series_frame = _prepare_history_frame(metric_series_history)
        metric_series_frame = metric_series_frame.dropna(subset=["metric_value_numeric"]).sort_values("checked_at")
        if metric_series_frame.empty:
            continue
        rendered_metric_frames.append(metric_series_frame)

    if not rendered_metric_frames:
        st.info("Belum ada data numerik untuk kombinasi filter device dan metric ini.")
        return

    chart_rows = [rendered_metric_frames[i:i + 1] for i in range(0, len(rendered_metric_frames), 1)]
    for row_frames in chart_rows:
        chart_columns = st.columns(1)
        for col_index, metric_frame in enumerate(row_frames):
            _render_metric_trend_section(
                metric_frame,
                chart_window_label=chart_window_label,
                target_column=chart_columns[col_index],
            )

    st.markdown("### Raw History")
    raw_history_frame = pd.concat(rendered_metric_frames, ignore_index=True).sort_values("checked_at", ascending=False)
    raw_view = raw_history_frame[
        ["checked_at_wib", "device_name", "metric_label", "display_value", "status"]
    ].rename(
        columns={
            "checked_at_wib": "Checked At (WIB)",
            "device_name": "Device",
            "metric_label": "Metric",
            "display_value": "Value",
            "status": "Status",
        }
    )
    st.dataframe(raw_view, width="stretch")


render_live_section(auto_refresh, interval_seconds, _render_history_body)
