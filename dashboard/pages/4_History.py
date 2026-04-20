from datetime import datetime, timedelta
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json, paged_items, paged_meta
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp, wib_date_boundary_to_utc_iso

st.set_page_config(page_title="History", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()


STATUS_OPTIONS = ["All", "up", "down", "ok", "error", "warning", "unknown"]
CHART_WINDOW_OPTIONS = {
    "1 jam": 1,
    "6 jam": 6,
    "12 jam": 12,
    "24 jam": 24,
    "7 hari": 24 * 7,
}
def _history_css() -> str:
    return """
<style>
.stMainBlockContainer,
[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 100%;
    padding-left: 2rem;
    padding-right: 2rem;
}
.history-meta,
.printer-panel,
.printer-status-chip,
.printer-ink-card {
    color: var(--text-color);
}
.history-meta {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin: 0.3rem 0 1.1rem 0;
}
.history-pill {
    border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
    background: transparent;
    border-radius: 999px;
    padding: 0.45rem 0.8rem;
    font-size: 0.9rem;
    color: color-mix(in srgb, var(--text-color) 58%, transparent);
}
.history-card-label {
    font-size: 0.9rem;
    line-height: 1.35;
    color: color-mix(in srgb, var(--text-color) 72%, transparent);
    margin-bottom: 0.6rem;
}
.history-card-content {
    display: flex;
    min-height: 92px;
    flex-direction: column;
    justify-content: flex-start;
}
.history-card-content p {
    margin: 0;
}
.history-card-value {
    font-size: clamp(1.35rem, 2vw, 2.5rem);
    line-height: 1.08;
    font-weight: 700;
    color: var(--text-color);
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.history-card-value.compact {
    font-size: clamp(1rem, 1.35vw, 1.4rem);
    line-height: 1.25;
}
.printer-panel {
    border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
    background: transparent;
    border-radius: 22px;
    padding: 1.25rem 1.25rem 1.1rem 1.25rem;
    margin: 0.25rem 0 1rem 0;
    box-shadow: none;
}
.printer-panel-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text-color);
    margin-bottom: 0.35rem;
}
.printer-panel-subtitle {
    font-size: 0.92rem;
    line-height: 1.5;
    color: color-mix(in srgb, var(--text-color) 72%, transparent);
    margin-bottom: 1rem;
}
.printer-status-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 0.85rem;
    margin-bottom: 0.9rem;
}
.printer-status-chip-label {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: color-mix(in srgb, var(--text-color) 58%, transparent);
    margin-bottom: 0.7rem;
}
.printer-status-chip-value {
    font-size: clamp(1.05rem, 1.45vw, 1.4rem);
    font-weight: 700;
    color: var(--text-color);
    line-height: 1.3;
    min-height: 2.25rem;
    display: flex;
    align-items: flex-start;
}
.printer-status-chip-meta {
    margin-top: auto;
    font-size: 0.8rem;
    color: color-mix(in srgb, var(--text-color) 72%, transparent);
    line-height: 1.5;
}
.printer-status-chip-content {
    display: flex;
    min-height: 112px;
    flex-direction: column;
    justify-content: flex-start;
    gap: 0.15rem;
}
.printer-status-chip-content p {
    margin: 0;
}
.printer-ink-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.85rem;
}
.printer-ink-card {
    border-radius: 18px;
    padding: 1rem;
    border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
    background: transparent;
    box-shadow: none;
}
.printer-ink-swatch {
    width: 14px;
    height: 14px;
    border-radius: 999px;
    margin-bottom: 0.7rem;
    border: 1px solid color-mix(in srgb, var(--text-color) 16%, transparent);
}
.printer-ink-value {
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--text-color);
    line-height: 1.1;
}
.printer-ink-caption {
    margin-top: 0.35rem;
    font-size: 0.85rem;
    color: color-mix(in srgb, var(--text-color) 72%, transparent);
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
    "printer_uptime_seconds": ("Printer Uptime", "Durasi hidup printer sejak reboot terakhir."),
    "printer_status": ("Printer Status", "Status umum printer dari SNMP Host Resources MIB."),
    "printer_error_state": ("Printer Error State", "Bitmask error printer yang sudah diterjemahkan ke label operasional."),
    "printer_ink_status": ("Ink Status", "Status tinta overall yang diturunkan dari status/error printer."),
    "printer_paper_status": ("Paper Status", "Kondisi kertas/tray printer berdasarkan SNMP."),
    "printer_total_pages": ("Total Pages", "Counter total halaman yang sudah tercetak."),
}
PRINTER_METRIC_NAMES = [
    "printer_uptime_seconds",
    "printer_status",
    "printer_error_state",
    "printer_ink_status",
    "printer_paper_status",
    "printer_total_pages",
]
INTERNET_ONLY_METRICS = {"dns_resolution_time", "http_response_time", "public_ip"}
PRINTER_DETAIL_ONLY_METRICS = {"printer_uptime_seconds", "printer_total_pages"}


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
    metric_name = str(row.get("metric_name") or "")
    metric_value = row.get("metric_value")
    metric_value_numeric = row.get("metric_value_numeric")
    if metric_name == "printer_uptime_seconds" and pd.notna(metric_value_numeric):
        return _format_duration(pd.Timedelta(seconds=float(metric_value_numeric)))
    if metric_name == "printer_total_pages" and pd.notna(metric_value_numeric):
        return f"{int(metric_value_numeric):,} pages"
    if metric_name == "printer_ink_status":
        return _humanize_printer_text(str(metric_value or "-"))
    if metric_name in {"printer_status", "printer_error_state", "printer_paper_status"}:
        return _humanize_printer_text(str(metric_value or "-"))
    unit = f' {row["unit"]}' if row.get("unit") else ""
    return f'{row["metric_value"]}{unit}'


def _friendly_metric_name(metric_name: str) -> str:
    return METRIC_LABELS.get(metric_name, (metric_name.replace("_", " ").title(), ""))[0]


def _metric_filter_label(metric_name: str) -> str:
    if metric_name == "All Metrics":
        return metric_name
    return f"{_friendly_metric_name(metric_name)} ({metric_name})"


def _humanize_printer_text(value: str) -> str:
    normalized = value.replace(",", ", ").replace("_", " ").strip()
    if not normalized:
        return "-"
    return normalized.title()


def _is_mikrotik_device(device_type: str | None, device_name: str | None) -> bool:
    normalized_type = str(device_type or "").lower()
    normalized_name = str(device_name or "").lower()
    return normalized_type == "mikrotik" or "mikrotik" in normalized_name


def _should_hide_metric_for_device(metric_name: str, device_type: str | None, device_name: str | None) -> bool:
    return _is_mikrotik_device(device_type, device_name) and metric_name in INTERNET_ONLY_METRICS


def _filter_metric_names(metric_names: list[str], device_type: str | None, device_name: str | None = None) -> list[str]:
    return [
        metric_name
        for metric_name in metric_names
        if not _should_hide_metric_for_device(metric_name, device_type, device_name)
        and not (device_type == "printer" and metric_name in PRINTER_DETAIL_ONLY_METRICS)
    ]


def _filter_history_rows(
    rows: list[dict],
    device_type_by_id: dict[int, str],
    device_name_by_id: dict[int, str],
) -> list[dict]:
    filtered_rows: list[dict] = []
    for row in rows:
        device_id = int(row.get("device_id", 0) or 0)
        device_type = device_type_by_id.get(device_id)
        device_name = device_name_by_id.get(device_id) or str(row.get("device_name") or "")
        metric_name = str(row.get("metric_name") or "")
        if _should_hide_metric_for_device(metric_name, device_type, device_name):
            continue
        filtered_rows.append(row)
    return filtered_rows


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
    dataframe["display_value"] = dataframe.apply(_format_metric_value, axis=1)
    return dataframe


def _fetch_device_history_rows(
    *,
    device_id: int,
    checked_from_date,
    checked_to_date,
    metric_names: list[str] | None = None,
    status: str | None = None,
) -> list[dict]:
    if metric_names:
        metric_name_set = {str(metric_name) for metric_name in metric_names}
        return [
            item
            for item in _fetch_history_pages(
                device_id=device_id,
                status=status,
                checked_from_date=checked_from_date,
                checked_to_date=checked_to_date,
            )
            if str(item.get("metric_name") or "") in metric_name_set
        ]

    return _fetch_history_pages(
        device_id=device_id,
        status=status,
        checked_from_date=checked_from_date,
        checked_to_date=checked_to_date,
    )


def _history_query_params(
    *,
    device_id: int,
    metric_name: str | None = None,
    status: str | None = None,
    checked_from_date=None,
    checked_to_date=None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, object]:
    query_params: dict[str, object] = {
        "limit": limit,
        "offset": offset,
        "device_id": device_id,
    }
    if metric_name:
        query_params["metric_name"] = metric_name
    if status and status != "All":
        query_params["status"] = status
    if checked_from_date:
        query_params["checked_from"] = wib_date_boundary_to_utc_iso(checked_from_date)
    if checked_to_date:
        query_params["checked_to"] = wib_date_boundary_to_utc_iso(checked_to_date, end_of_day=True)
    return query_params


def _fetch_history_pages(
    *,
    device_id: int,
    metric_name: str | None = None,
    status: str | None = None,
    checked_from_date=None,
    checked_to_date=None,
) -> list[dict]:
    page_size = 500
    offset = 0
    items: list[dict] = []

    while True:
        query_params = _history_query_params(
            device_id=device_id,
            metric_name=metric_name,
            status=status,
            checked_from_date=checked_from_date,
            checked_to_date=checked_to_date,
            limit=page_size,
            offset=offset,
        )
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


def _render_stat_card(column, label: str, value: str | int, *, compact: bool = False) -> None:
    value_class = "history-card-value compact" if compact else "history-card-value"
    with column.container(border=True):
        st.markdown(
            f"""
            <div class="history-card-content">
                <div class="history-card-label">{label}</div>
                <div class="{value_class}">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _latest_metric_snapshot_map(dataframe: pd.DataFrame) -> dict[str, pd.Series]:
    if dataframe.empty:
        return {}
    latest_rows = dataframe.sort_values("checked_at").drop_duplicates(subset=["metric_name"], keep="last")
    return {str(row["metric_name"]): row for _, row in latest_rows.iterrows()}


def _printer_chip(label: str, value: str, meta: str = "") -> str:
    meta_markup = f'<div class="printer-status-chip-meta">{meta}</div>' if meta else ""
    return f"""
    <div class="printer-status-chip-content">
        <div class="printer-status-chip-label">{label}</div>
        <div class="printer-status-chip-value">{value}</div>
        {meta_markup}
    </div>
    """


def _render_printer_history_section(
    printer_history_frame: pd.DataFrame,
) -> None:
    if printer_history_frame.empty:
        st.info("Belum ada metric printer SNMP yang tersimpan untuk device ini.")
        return

    latest_map = _latest_metric_snapshot_map(printer_history_frame)
    status_row = latest_map.get("printer_status")
    error_row = latest_map.get("printer_error_state")
    ink_status_row = latest_map.get("printer_ink_status")
    paper_row = latest_map.get("printer_paper_status")
    uptime_row = latest_map.get("printer_uptime_seconds")
    pages_row = latest_map.get("printer_total_pages")
    st.markdown(
        """
        <div class="printer-panel">
            <div class="printer-panel-title">Printer Health</div>
            <div class="printer-panel-subtitle">
                Ringkasan cepat untuk status printer, deteksi gangguan, uptime sejak reboot, dan counter halaman.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    status_columns = st.columns(6)
    status_cards = [
        (
            "Overall Status",
            str(status_row["display_value"]) if status_row is not None else "-",
            f"Status metric: {str(status_row['status']).upper()}" if status_row is not None else "",
        ),
        (
            "Error State",
            str(error_row["display_value"]) if error_row is not None else "-",
            f"Severity: {str(error_row['status']).upper()}" if error_row is not None else "",
        ),
        (
            "Paper Status",
            str(paper_row["display_value"]) if paper_row is not None else "-",
            f"Status metric: {str(paper_row['status']).upper()}" if paper_row is not None else "",
        ),
        (
            "Ink Status",
            str(ink_status_row["display_value"]) if ink_status_row is not None else "-",
            "Overall consumable state dari printer",
        ),
        (
            "Uptime",
            str(uptime_row["display_value"]) if uptime_row is not None else "-",
            "Dipakai untuk deteksi reboot",
        ),
        (
            "Total Pages",
            str(pages_row["display_value"]) if pages_row is not None else "-",
            "Counter akumulatif printer",
        ),
    ]
    for column, (label, value, meta) in zip(status_columns, status_cards, strict=False):
        with column.container(border=True):
            st.markdown(_printer_chip(label, value, meta), unsafe_allow_html=True)

st.markdown(_history_css(), unsafe_allow_html=True)
st.title("History")
st.caption("Halaman ini menampilkan histori pengecekan metric. Pilih device dan metric supaya grafik lebih jelas dibaca.")

devices_payload = get_json("/devices/paged?active_only=false&limit=1000&offset=0", {"items": [], "meta": {}})
devices = paged_items(devices_payload)
device_type_by_id = {
    int(device["id"]): str(device.get("device_type") or "")
    for device in devices
}
device_name_by_id = {
    int(device["id"]): str(device.get("name") or "")
    for device in devices
}
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
    if "history_chart_window" not in st.session_state:
        st.session_state["history_chart_window"] = "1 jam"
    device_option_labels = list(device_options.keys())
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    selected_device = filter_col1.selectbox(
        "Device",
        options=device_option_labels,
        index=device_option_labels.index(default_device_label),
        key="history_selected_device",
    )
    selected_device_id = device_options[selected_device]
    selected_device_record = next((device for device in devices if device["id"] == selected_device_id), None)
    selected_device_type = str(selected_device_record.get("device_type")) if selected_device_record else None
    current_selected_metric = str(st.session_state.get("history_selected_metric", "All Metrics"))
    status_value = filter_col3.selectbox("Status", options=STATUS_OPTIONS, index=0)
    limit_value = filter_col4.selectbox("Rows", options=[50, 100, 200, 300, 500], index=2)
    chart_window_label = st.selectbox(
        "Chart Window",
        options=list(CHART_WINDOW_OPTIONS.keys()),
        index=list(CHART_WINDOW_OPTIONS.keys()).index("1 jam"),
        help="Pilih rentang waktu yang dipakai untuk chart trend.",
        key="history_chart_window",
    )
    date_filter_col1, date_filter_col2 = st.columns(2)
    checked_from_date = date_filter_col1.date_input("Checked From", value=default_start_date)
    checked_to_date = date_filter_col2.date_input("Checked To", value=today)

    snapshot_page_size = int(st.session_state.get("history_snapshot_page_size", 10))
    snapshot_page = int(st.session_state.get("history_snapshot_page", 1))
    snapshot_offset = (snapshot_page - 1) * snapshot_page_size
    context_query_params = {
        "limit": limit_value,
        "selected_device_limit": limit_value,
        "snapshot_limit": snapshot_page_size,
        "snapshot_offset": snapshot_offset,
    }
    if selected_device_id is not None:
        context_query_params["device_id"] = selected_device_id
    if current_selected_metric != "All Metrics" and not _should_hide_metric_for_device(
        current_selected_metric,
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    ):
        context_query_params["metric_name"] = current_selected_metric
    if checked_from_date:
        context_query_params["checked_from"] = wib_date_boundary_to_utc_iso(checked_from_date)
    if checked_to_date:
        context_query_params["checked_to"] = wib_date_boundary_to_utc_iso(checked_to_date, end_of_day=True)
    if status_value != "All":
        context_query_params["status"] = status_value
    history_context = get_json(
        f"/metrics/history/context?{urlencode(context_query_params)}",
        {
            "metric_names": [],
            "history": {"items": [], "meta": {}},
            "selected_device_history": {"items": [], "meta": {}},
            "latest_snapshot": {"items": [], "meta": {}},
            "latest_snapshot_status_summary": {},
            "snapshot_uptime_map": {},
        },
    )
    metric_name_options = _filter_metric_names(
        history_context.get("metric_names", []),
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    if (
        _is_mikrotik_device(
            selected_device_type,
            selected_device_record.get("name") if selected_device_record else None,
        )
        and st.session_state.get("history_selected_metric") in INTERNET_ONLY_METRICS
    ):
        st.session_state["history_selected_metric"] = "All Metrics"
    metric_select_options = ["All Metrics"] + metric_name_options
    selected_metric = filter_col2.selectbox(
        "Metric Name",
        options=metric_select_options,
        index=0,
        format_func=_metric_filter_label,
        help="Daftar metric yang sudah tersimpan di history.",
        key="history_selected_metric",
    )
    history_payload = history_context.get("history", {"items": [], "meta": {}})
    selected_device_history_payload = history_context.get("selected_device_history", {"items": [], "meta": {}})
    selected_device_history_raw = paged_items(selected_device_history_payload)
    history = paged_items(history_payload)
    history_meta = paged_meta(history_payload)
    history = _filter_history_rows(history, device_type_by_id, device_name_by_id)
    selected_device_history = _filter_history_rows(selected_device_history_raw, device_type_by_id, device_name_by_id)
    full_device_history = selected_device_history
    if selected_device_id is not None:
        metric_names = None if selected_metric == "All Metrics" else [selected_metric]
        full_device_history = _filter_history_rows(
            _fetch_device_history_rows(
                device_id=selected_device_id,
                checked_from_date=checked_from_date,
                checked_to_date=checked_to_date,
                metric_names=metric_names,
                status=status_value,
            ),
            device_type_by_id,
            device_name_by_id,
        )
    elif selected_metric != "All Metrics":
        full_device_history = [
            row for row in full_device_history if str(row.get("metric_name") or "") == selected_metric
        ]

    snapshot_payload = history_context.get("latest_snapshot", {"items": [], "meta": {}})
    snapshot_history = _filter_history_rows(paged_items(snapshot_payload), device_type_by_id, device_name_by_id)
    snapshot_meta = paged_meta(snapshot_payload)
    st.session_state["history_snapshot_total"] = int(snapshot_meta.get("total", 0) or 0)
    snapshot_uptime_map = history_context.get("snapshot_uptime_map", {})
    latest_snapshot_status_summary = history_context.get("latest_snapshot_status_summary", {})
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
    latest_per_series["uptime"] = latest_per_series.apply(
        lambda row: _format_duration(
            pd.Timedelta(seconds=float(snapshot_uptime_map.get(f'{int(row["device_id"])}:{row["metric_name"]}', 0)))
        )
        if str(snapshot_uptime_map.get(f'{int(row["device_id"])}:{row["metric_name"]}', "-")) not in {"", "-"}
        else "-",
        axis=1,
    )

    with summary_container:
        summary_col1, summary_col2, summary_col3 = st.columns(3)
        _render_stat_card(summary_col1, "Rows Loaded", int(len(dataframe)))
        _render_stat_card(summary_col2, "Latest Check", format_wib_timestamp(latest_timestamp), compact=True)
        _render_stat_card(summary_col3, "Total Devices", int(len(devices)))

    with snapshot_container:
        st.markdown("### Latest Snapshot")
        st.caption(
            f"Menampilkan {len(latest_per_series)} dari total {snapshot_meta.get('total', len(latest_per_series))} snapshot terbaru."
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
        _snapshot_pagination_controls(int(snapshot_meta.get("total", len(latest_per_series))))

    with status_container:
        st.markdown("### Status Summary")
        status_counts = (
            pd.DataFrame(
                [{"status": status, "count": count} for status, count in latest_snapshot_status_summary.items()]
            ).sort_values(["count", "status"], ascending=[False, True])
            if latest_snapshot_status_summary
            else pd.DataFrame(columns=["status", "count"])
        )
        status_left, status_right = st.columns([1, 2])
        status_left.dataframe(status_counts, width="stretch", hide_index=True)
        if status_counts.empty:
            status_right.info("Belum ada status device untuk diringkas.")
        else:
            status_right.bar_chart(status_counts.set_index("status"))

    if selected_device_id is not None and selected_device_type == "printer":
        printer_history = [
            row for row in selected_device_history if str(row.get("metric_name") or "") in PRINTER_METRIC_NAMES
        ]
        printer_history_frame = _prepare_history_frame(printer_history, sort_desc=False)
        _render_printer_history_section(printer_history_frame)

    st.markdown("### Metric Trend")
    if selected_device_id is None:
        st.info("Pilih satu device dari filter di atas supaya chart trend bisa ditampilkan.")
        return

    numeric_frame = dataframe.dropna(subset=["metric_value_numeric"]).copy()
    if numeric_frame.empty:
        st.info("Tidak ada metric numerik pada filter ini, jadi grafik trend belum bisa ditampilkan.")
        return

    device_history_frame = _prepare_history_frame(full_device_history, sort_desc=False)
    if device_history_frame.empty:
        st.info("Belum ada history lengkap untuk device ini pada rentang waktu yang dipilih.")
        return

    metric_names_to_render = (
        [selected_metric]
        if selected_metric != "All Metrics"
        else sorted(device_history_frame["metric_name"].dropna().unique().tolist())
    )
    metric_names_to_render = _filter_metric_names(
        metric_names_to_render,
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    rendered_metric_frames: list[pd.DataFrame] = []
    for metric_name in metric_names_to_render:
        metric_series_frame = device_history_frame[device_history_frame["metric_name"] == str(metric_name)].copy()
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
    if selected_device_id is not None and selected_device_type == "printer":
        raw_history_frame = (
            device_history_frame if not device_history_frame.empty else dataframe.copy()
        ).sort_values("checked_at", ascending=False)
    else:
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
