"""Live monitoring helper functions extracted from page module."""

from datetime import datetime, timedelta
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import streamlit as st

from shared.device_utils import format_device_label, is_mikrotik_device
from components.auth import require_dashboard_login
from components.api import get_json, paged_items, paged_meta
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp, wib_date_boundary_to_utc_iso
from components.ui import normalize_status_label, render_meta_row, render_page_header, status_priority

STATUS_OPTIONS = ["All", "up", "down", "ok", "error", "warning", "unknown"]
CHART_WINDOW_OPTIONS = {
    "1 jam": 1,
    "6 jam": 6,
    "12 jam": 12,
    "24 jam": 24,
    "7 hari": 24 * 7,
}
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
    "memory_used_bytes": ("Memory Used", "Memori terpakai dari Mikrotik."),
    "memory_free_bytes": ("Memory Free", "Memori kosong dari Mikrotik."),
    "disk_used_bytes": ("Storage Used", "Storage terpakai dari Mikrotik."),
    "disk_free_bytes": ("Storage Free", "Storage kosong dari Mikrotik."),
    "boot_time_epoch": ("Boot Time", "Waktu boot terakhir dalam epoch timestamp."),
    "interfaces_running": ("Active Interfaces", "Jumlah interface Mikrotik yang sedang running."),
    "dhcp_active_leases": ("DHCP Active Leases", "Jumlah lease DHCP aktif/bound di Mikrotik."),
    "connected_clients": ("Connected Clients", "Jumlah client unik dari DHCP lease aktif dan ARP table."),
    "mikrotik_api": ("Mikrotik API Status", "Status koneksi ke API Mikrotik."),
    "printer_uptime_seconds": ("Printer Uptime", "Durasi hidup printer sejak reboot terakhir."),
    "printer_status": ("Printer Status", "Status umum printer dari SNMP Host Resources MIB."),
    "printer_error_state": ("Status Error Printer", "Bitmask error printer yang sudah diterjemahkan ke label operasional."),
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


def _default_device_option_label(devices: list[dict]) -> str:
    internet_targets = [device for device in devices if device.get("device_type") == "internet_target"]
    if not internet_targets:
        return "Semua Device"

    preferred_device = next(
        (device for device in internet_targets if "myrepublic" in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return format_device_label(preferred_device)

    preferred_device = next(
        (device for device in internet_targets if "isp" in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return format_device_label(preferred_device)

    preferred_device = next(
        (device for device in internet_targets if "mikrotik" not in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return format_device_label(preferred_device)
    return "Semua Device"


def _format_metric_value(row: pd.Series) -> str:
    return _format_metric_value_components(
        metric_name=str(row.get("metric_name") or ""),
        metric_value=row.get("metric_value"),
        metric_value_numeric=row.get("metric_value_numeric"),
        unit=row.get("unit"),
    )


def _format_metric_value_components(
    *,
    metric_name: str,
    metric_value,
    metric_value_numeric,
    unit,
) -> str:
    metric_name = str(metric_name or "")
    if metric_name == "printer_uptime_seconds" and pd.notna(metric_value_numeric):
        return _format_duration(pd.Timedelta(seconds=float(metric_value_numeric)))
    if metric_name == "printer_total_pages" and pd.notna(metric_value_numeric):
        return f"{int(metric_value_numeric):,} pages"
    if metric_name == "printer_ink_status":
        return _humanize_printer_text(str(metric_value or "-"))
    if metric_name in {"printer_status", "printer_error_state", "printer_paper_status"}:
        return _humanize_printer_text(str(metric_value or "-"))
    unit_suffix = f" {unit}" if unit else ""
    return f"{metric_value}{unit_suffix}"


def _friendly_metric_name(metric_name: str) -> str:
    dynamic_label = _dynamic_mikrotik_metric_label(metric_name)
    if dynamic_label:
        return dynamic_label
    return METRIC_LABELS.get(metric_name, (metric_name.replace("_", " ").title(), ""))[0]


def _metric_filter_label(metric_name: str) -> str:
    if metric_name == "All Metrics":
        return "Semua Metrik"
    return f"{_friendly_metric_name(metric_name)} ({metric_name})"


def _dynamic_mikrotik_metric_label(metric_name: str) -> str | None:
    parts = str(metric_name or "").split(":")
    if len(parts) < 3:
        return None
    category = parts[0]
    name = parts[1].replace("_", " ").title()
    metric_key = parts[-1]
    metric_labels = {
        "rx_bytes": "RX Bytes",
        "tx_bytes": "TX Bytes",
        "rx_mbps": "RX Mbps",
        "tx_mbps": "TX Mbps",
        "packets": "Packets",
        "bytes": "Bytes",
        "pps": "Packets/s",
        "mbps": "Mbps",
    }
    suffix = metric_labels.get(metric_key, metric_key.replace("_", " ").title())
    if category == "interface":
        return f"Interface {name} {suffix}"
    if category == "queue":
        return f"Queue {name} {suffix}"
    if category == "firewall" and len(parts) >= 4:
        section = parts[1].upper()
        rule = parts[2].replace("_", " ").title()
        return f"Firewall {section} {rule} {suffix}"
    return None


def _humanize_printer_text(value: str) -> str:
    normalized = value.replace(",", ", ").replace("_", " ").strip()
    if not normalized:
        return "-"
    return normalized.title()


def _should_hide_metric_for_device(metric_name: str, device_type: str | None, device_name: str | None) -> bool:
    return is_mikrotik_device(device_type, device_name) and metric_name in INTERNET_ONLY_METRICS


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
    metric_names = dataframe["metric_name"].dropna().astype(str).unique()
    metric_label_map = {metric_name: _friendly_metric_name(metric_name) for metric_name in metric_names}
    dataframe["metric_label"] = dataframe["metric_name"].astype(str).map(metric_label_map)
    dataframe["checked_at_wib"] = dataframe["checked_at"].map(format_wib_timestamp)
    dataframe["display_value"] = _format_metric_values(dataframe)
    dataframe["status"] = dataframe["status"].map(normalize_status_label)
    return dataframe


def _format_metric_values(dataframe: pd.DataFrame) -> pd.Series:
    unit_suffix = dataframe["unit"].map(lambda unit: f" {unit}" if unit else "")
    display_values = dataframe["metric_value"].astype(str) + unit_suffix
    numeric_values = pd.to_numeric(dataframe["metric_value_numeric"], errors="coerce")
    metric_names = dataframe["metric_name"].astype(str)

    uptime_mask = metric_names.eq("printer_uptime_seconds") & numeric_values.notna()
    if uptime_mask.any():
        display_values.loc[uptime_mask] = numeric_values.loc[uptime_mask].map(
            lambda value: _format_duration(pd.Timedelta(seconds=float(value)))
        )

    pages_mask = metric_names.eq("printer_total_pages") & numeric_values.notna()
    if pages_mask.any():
        display_values.loc[pages_mask] = numeric_values.loc[pages_mask].map(lambda value: f"{int(value):,} pages")

    humanized_mask = metric_names.isin(
        {"printer_ink_status", "printer_status", "printer_error_state", "printer_paper_status"}
    )
    if humanized_mask.any():
        display_values.loc[humanized_mask] = dataframe.loc[humanized_mask, "metric_value"].map(
            lambda value: _humanize_printer_text(str(value or "-"))
        )

    return display_values


def _fetch_device_history_rows(
    *,
    device_id: int,
    checked_from_date,
    checked_to_date,
    metric_names: list[str] | None = None,
    status: str | None = None,
    max_pages: int | None = None,
    initial_payload: dict | None = None,
) -> list[dict]:
    if metric_names:
        unique_metric_names = list(dict.fromkeys(str(metric_name) for metric_name in metric_names))
        if max_pages == 1:
            return _fetch_history_rows_bulk(
                device_id=device_id,
                metric_names=unique_metric_names,
                status=status,
                checked_from_date=checked_from_date,
                checked_to_date=checked_to_date,
                per_metric_limit=500,
            )

        items: list[dict] = []
        for metric_name in unique_metric_names:
            items.extend(
                _fetch_history_pages(
                    device_id=device_id,
                    metric_name=metric_name,
                    status=status,
                    checked_from_date=checked_from_date,
                    checked_to_date=checked_to_date,
                    max_pages=max_pages,
                    initial_payload=initial_payload if len(unique_metric_names) == 1 else None,
                )
            )
        return items

    return _fetch_history_pages(
        device_id=device_id,
        status=status,
        checked_from_date=checked_from_date,
        checked_to_date=checked_to_date,
        max_pages=max_pages,
        initial_payload=initial_payload,
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
    metric_names: list[str] | None = None,
    per_metric_limit: int | None = None,
) -> dict[str, object]:
    query_params: dict[str, object] = {
        "limit": limit,
        "offset": offset,
        "device_id": device_id,
    }
    if metric_name:
        query_params["metric_name"] = metric_name
    if metric_names:
        query_params["metric_names"] = metric_names
    if per_metric_limit is not None:
        query_params["per_metric_limit"] = per_metric_limit
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
    max_pages: int | None = None,
    initial_payload: dict | None = None,
) -> list[dict]:
    page_size = 500
    offset = 0
    items: list[dict] = []
    next_payload = initial_payload

    while True:
        if next_payload is None:
            query_params = _history_query_params(
                device_id=device_id,
                metric_name=metric_name,
                status=status,
                checked_from_date=checked_from_date,
                checked_to_date=checked_to_date,
                limit=page_size,
                offset=offset,
            )
            payload = get_json(f"/metrics/history/paged?{urlencode(query_params, doseq=True)}", {"items": [], "meta": {}})
        else:
            payload = next_payload
            next_payload = None
        page_items = paged_items(payload)
        if not page_items:
            break

        items.extend(page_items)
        meta = paged_meta(payload)
        offset = int(meta.get("offset", offset) or 0) + len(page_items)
        total = int(meta.get("total", 0) or 0)
        if offset >= total:
            break
        if max_pages is not None and offset >= page_size * max_pages:
            break

    return items


def _fetch_history_rows_bulk(
    *,
    device_id: int,
    metric_names: list[str],
    status: str | None = None,
    checked_from_date=None,
    checked_to_date=None,
    per_metric_limit: int = 500,
) -> list[dict]:
    if not metric_names:
        return []
    query_params = _history_query_params(
        device_id=device_id,
        metric_names=metric_names,
        status=status,
        checked_from_date=checked_from_date,
        checked_to_date=checked_to_date,
        # Backend applies per-metric limiting when metric_names + per_metric_limit
        # are provided, and still validates `limit` <= 500.
        limit=500,
        offset=0,
        per_metric_limit=per_metric_limit,
    )
    payload = get_json(f"/metrics/history/paged?{urlencode(query_params, doseq=True)}", {"items": [], "meta": {}})
    return paged_items(payload)


def _fetch_latest_device_snapshot(device_id: int, limit: int = 500) -> list[dict]:
    payload = get_json(
        f"/metrics/latest-snapshot/paged?{urlencode({'device_id': device_id, 'limit': limit, 'offset': 0})}",
        {"items": [], "meta": {}},
    )
    return paged_items(payload)


def _latest_snapshot_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    return dataframe.drop_duplicates(subset=["device_name", "metric_name"]).copy()


def _snapshot_pagination_controls(total_rows: int) -> tuple[int, int]:
    page_size_col, page_col, _ = st.columns([1, 1, 4])
    default_page_size = int(st.session_state.get("history_snapshot_page_size", 10))
    if default_page_size not in [10, 25, 50, 100]:
        default_page_size = 10
    page_size = page_size_col.selectbox(
        "Baris Snapshot",
        options=[10, 25, 50, 100],
        index=[10, 25, 50, 100].index(default_page_size),
        key="history_snapshot_page_size",
    )
    total_pages = max((total_rows - 1) // page_size + 1, 1)
    page_number = page_col.number_input(
        "Halaman Snapshot",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("history_snapshot_page", 1), total_pages),
        step=1,
        key="history_snapshot_page",
    )
    return int(page_size), int(page_number)


def _paginate_frame(dataframe: pd.DataFrame, *, key_prefix: str, page_size: int = 10) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe
    total_rows = len(dataframe)
    total_pages = max((total_rows - 1) // page_size + 1, 1)
    page_key = f"{key_prefix}_page"
    current_page = min(int(st.session_state.get(page_key, 1)), total_pages)
    page_col, meta_col = st.columns([1, 5])
    page_number = page_col.number_input(
        "Halaman Data",
        min_value=1,
        max_value=total_pages,
        value=current_page,
        step=1,
        key=page_key,
    )
    start = (int(page_number) - 1) * page_size
    end = start + page_size
    meta_col.caption(f"Menampilkan {start + 1}-{min(end, total_rows)} dari {total_rows} baris.")
    return dataframe.iloc[start:end].copy()


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
    sample_count = int(len(chart_metric_frame))
    previous_value = (
        float(chart_metric_frame["metric_value_numeric"].iloc[-2])
        if sample_count > 1
        else None
    )
    latest_value = float(latest_metric_row["metric_value_numeric"])
    delta_value = latest_value - previous_value if previous_value is not None else None
    trend_text = _trend_direction_text(delta_value)

    unit_suffix = f" ({metric_unit})" if metric_unit else ""
    container.markdown(f"#### {metric_label} - {metric_device_name}")
    container.caption(
        f"Nilai terakhir {_format_metric_value(latest_metric_row)} | "
        f"{trend_text} | "
        f"Rentang {chart_min:.2f} - {chart_max:.2f}{unit_suffix} | "
        f"{sample_count} sampel ({chart_window_label})"
    )
    stat_col1, stat_col2, stat_col3, stat_col4 = container.columns(4)
    _render_stat_card(stat_col1, "Nilai Terakhir", _format_metric_value(latest_metric_row))
    _render_stat_card(stat_col2, "Arah", trend_text)
    _render_stat_card(stat_col3, "Rata-rata", _format_metric_numeric(chart_avg, metric_unit))
    _render_stat_card(stat_col4, "Status", _status_label_for_display(latest_metric_row["status"]))

    chart_title = f"Tren {metric_label} - {metric_device_name}"
    avg_frame = pd.DataFrame([{"line_label": "Rata-rata", "line_value": chart_avg}])
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
                alt.Tooltip("checked_at_wib:N", title="Dicek"),
                alt.Tooltip("device_name:N", title="Device"),
                alt.Tooltip("metric_label:N", title="Metrik"),
                alt.Tooltip("display_value:N", title="Nilai"),
                alt.Tooltip("status:N", title="Status"),
            ],
        )
    )
    reference_lines = (
        alt.Chart(avg_frame)
        .mark_rule(strokeDash=[6, 4], strokeWidth=1.5)
        .encode(
            y=alt.Y("line_value:Q"),
            color=alt.Color(
                "line_label:N",
                title="Referensi",
                scale=alt.Scale(
                    domain=["Rata-rata"],
                    range=["#22c55e"],
                ),
            ),
            tooltip=[
                alt.Tooltip("line_label:N", title="Garis"),
                alt.Tooltip("line_value:Q", title="Nilai", format=".2f"),
            ],
        )
    )
    chart = (line_chart + reference_lines).properties(title=chart_title, height=280)
    container.altair_chart(chart, width="stretch")


def _render_stat_card(column, label: str, value: str | int, *, compact: bool = False) -> None:
    with column.container(border=True):
        st.metric(label, value)


def _status_counts_frame(
    latest_snapshot_status_summary: dict[str, int],
    fallback_frame: pd.DataFrame,
) -> pd.DataFrame:
    if latest_snapshot_status_summary:
        status_counts = pd.DataFrame(
            [{"status": normalize_status_label(status), "Jumlah": count} for status, count in latest_snapshot_status_summary.items()]
        )
    elif not fallback_frame.empty:
        counts = fallback_frame["status"].fillna("Unknown").map(normalize_status_label).value_counts()
        status_counts = pd.DataFrame({"status": counts.index.tolist(), "Jumlah": counts.values.tolist()})
    else:
        status_counts = pd.DataFrame(columns=["status", "Jumlah"])
    if status_counts.empty:
        return status_counts
    status_counts["priority"] = status_counts["status"].map(status_priority)
    return status_counts.sort_values(["priority", "Jumlah", "status"], ascending=[True, False, True]).reset_index(drop=True)


def _status_color_scale() -> alt.Scale:
    return alt.Scale(
        domain=["Down", "Error", "Warning", "Unknown", "Active", "Resolved", "OK", "Up"],
        range=["#dc2626", "#ef4444", "#f59e0b", "#6b7280", "#3b82f6", "#10b981", "#22c55e", "#16a34a"],
    )


def _health_score_percent(status_counts: pd.DataFrame) -> int:
    if status_counts.empty:
        return 0
    total = int(status_counts["Jumlah"].sum())
    if total <= 0:
        return 0
    weighted_score = 0.0
    status_weights = {
        "Up": 1.0,
        "OK": 1.0,
        "Resolved": 0.8,
        "Active": 0.6,
        "Warning": 0.5,
        "Unknown": 0.3,
        "Error": 0.0,
        "Down": 0.0,
    }
    for _, row in status_counts.iterrows():
        weighted_score += float(row.get("Jumlah", 0) or 0) * float(status_weights.get(str(row.get("status") or ""), 0.4))
    return max(0, min(100, round((weighted_score / total) * 100)))


def _entity_volume_frame(dataframe: pd.DataFrame, column_name: str, label_name: str, top_n: int = 6) -> pd.DataFrame:
    if dataframe.empty or column_name not in dataframe.columns:
        return pd.DataFrame(columns=[label_name, "Jumlah"])
    grouped = (
        dataframe[column_name]
        .fillna("-")
        .astype(str)
        .value_counts()
        .head(top_n)
        .reset_index()
    )
    grouped.columns = [label_name, "Jumlah"]
    return grouped


def _recent_anomaly_frame(dataframe: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame()
    anomaly_statuses = {"Warning", "Down", "Error"}
    anomaly_frame = dataframe[dataframe["status"].isin(anomaly_statuses)].copy()
    if anomaly_frame.empty:
        return anomaly_frame
    return anomaly_frame.sort_values("checked_at", ascending=False).head(top_n)


def _format_metric_numeric(value: float | int | None, unit: str | None = None) -> str:
    if value is None or pd.isna(value):
        return "-"
    suffix = f" {unit}" if unit else ""
    return f"{float(value):.2f}{suffix}"


def _trend_direction_text(delta_value: float | None) -> str:
    if delta_value is None or pd.isna(delta_value):
        return "Stabil (data awal)"
    if abs(float(delta_value)) < 1e-9:
        return "Stabil (0)"
    direction = "Naik" if float(delta_value) > 0 else "Turun"
    return f"{direction} {abs(float(delta_value)):.2f}"


def _metric_kpi_summary(metric_frame: pd.DataFrame) -> dict[str, object]:
    if metric_frame.empty:
        return {}
    ordered = metric_frame.sort_values("checked_at").copy()
    latest_row = ordered.iloc[-1]
    latest_value_numeric = pd.to_numeric(latest_row.get("metric_value_numeric"), errors="coerce")
    previous_value = (
        float(ordered["metric_value_numeric"].iloc[-2])
        if len(ordered) > 1 and pd.notna(ordered["metric_value_numeric"].iloc[-2])
        else None
    )
    delta_value = (
        float(latest_value_numeric) - previous_value
        if pd.notna(latest_value_numeric) and previous_value is not None
        else None
    )
    numeric_series = pd.to_numeric(ordered["metric_value_numeric"], errors="coerce")
    unit = latest_row.get("unit")
    return {
        "metric_label": _friendly_metric_name(str(latest_row.get("metric_name") or "")),
        "device_name": str(latest_row.get("device_name") or "-"),
        "latest_display": _format_metric_value(latest_row),
        "latest_numeric": float(latest_value_numeric) if pd.notna(latest_value_numeric) else None,
        "avg": float(numeric_series.mean()) if numeric_series.notna().any() else None,
        "min": float(numeric_series.min()) if numeric_series.notna().any() else None,
        "max": float(numeric_series.max()) if numeric_series.notna().any() else None,
        "count": int(len(ordered)),
        "status": _status_label_for_display(latest_row.get("status")),
        "delta": delta_value,
        "unit": str(unit) if unit else None,
    }


def _raw_history_view(raw_history_frame: pd.DataFrame, *, metric_selected: bool) -> pd.DataFrame:
    if raw_history_frame.empty:
        return pd.DataFrame(columns=["Dicek (WIB)", "Nilai", "Status", "Device", "Metrik"])
    if not metric_selected:
        return raw_history_frame[
            ["checked_at_wib", "device_name", "metric_label", "display_value", "status"]
        ].rename(
            columns={
                "checked_at_wib": "Dicek (WIB)",
                "device_name": "Device",
                "metric_label": "Metrik",
                "display_value": "Nilai",
                "status": "Status",
            }
        )

    enriched = raw_history_frame.sort_values("checked_at").copy()
    enriched["numeric_value"] = pd.to_numeric(enriched["metric_value_numeric"], errors="coerce")
    enriched["delta_numeric"] = enriched["numeric_value"].diff()
    enriched["Nilai Numerik"] = enriched.apply(
        lambda row: _format_metric_numeric(row.get("numeric_value"), row.get("unit")),
        axis=1,
    )
    enriched["Perubahan"] = enriched["delta_numeric"].map(
        lambda value: "-" if pd.isna(value) else f"{value:+.2f}"
    )
    enriched["Catatan"] = "-"
    numeric_series = enriched["numeric_value"]
    if numeric_series.notna().any():
        max_value = float(numeric_series.max())
        min_value = float(numeric_series.min())
        enriched.loc[numeric_series.eq(max_value), "Catatan"] = "Puncak window"
        enriched.loc[numeric_series.eq(min_value), "Catatan"] = "Terendah window"
    enriched = enriched.sort_values("checked_at", ascending=False)
    return enriched[
        ["checked_at_wib", "display_value", "Nilai Numerik", "Perubahan", "status", "device_name", "metric_label", "Catatan"]
    ].rename(
        columns={
            "checked_at_wib": "Dicek (WIB)",
            "display_value": "Nilai",
            "status": "Status",
            "device_name": "Device",
            "metric_label": "Metrik",
        }
    )


def _status_label_for_display(status_value: object) -> str:
    normalized = str(status_value or "").strip().lower()
    if normalized in {"down", "error"}:
        return f"Tinggi | {normalize_status_label(normalized)}"
    if normalized == "warning":
        return f"Sedang | {normalize_status_label(normalized)}"
    if normalized in {"up", "ok"}:
        return f"Normal | {normalize_status_label(normalized)}"
    return f"Info | {normalize_status_label(normalized)}"


def _non_numeric_metric_timeline(metric_frame: pd.DataFrame) -> pd.DataFrame:
    if metric_frame.empty:
        return pd.DataFrame(columns=["Dicek (WIB)", "Nilai", "Status", "Device", "Metrik"])
    ordered = metric_frame.sort_values("checked_at", ascending=False).copy()
    ordered["status_display"] = ordered["status"].map(_status_label_for_display)
    return ordered[
        ["checked_at_wib", "display_value", "status_display", "device_name", "metric_label"]
    ].rename(
        columns={
            "checked_at_wib": "Dicek (WIB)",
            "display_value": "Nilai",
            "status_display": "Status",
            "device_name": "Device",
            "metric_label": "Metrik",
        }
    )


def _latest_metric_snapshot_map(dataframe: pd.DataFrame) -> dict[str, pd.Series]:
    if dataframe.empty:
        return {}
    latest_rows = dataframe.sort_values("checked_at").drop_duplicates(subset=["metric_name"], keep="last")
    return {str(row["metric_name"]): row for _, row in latest_rows.iterrows()}


def _latest_metric_value_from_map(
    latest_map: dict[str, pd.Series],
    metric_name: str,
    default: str = "-",
) -> str:
    row = latest_map.get(metric_name)
    if row is None:
        return default
    return str(row.get("metric_value") or default)


def _format_percent(value: str) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _format_bytes(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "-"


def _format_mbps(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def _dynamic_mikrotik_metric_table(dataframe: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame()

    latest_rows = dataframe.sort_values("checked_at").drop_duplicates(subset=["metric_name"], keep="last")
    rows = latest_rows[latest_rows["metric_name"].astype(str).str.startswith(f"{prefix}:")].copy()
    if rows.empty:
        return pd.DataFrame()

    parsed_rows = []
    for _, row in rows.iterrows():
        parts = str(row["metric_name"]).split(":")
        if prefix == "firewall":
            if len(parts) < 4:
                continue
            group_key = (parts[1], parts[2])
            metric_key = parts[3]
            label = f"{parts[1]} / {parts[2].replace('_', ' ')}"
        else:
            if len(parts) < 3:
                continue
            group_key = parts[1]
            metric_key = parts[2]
            label = parts[1].replace("_", " ")
        parsed_rows.append(
            {
                "group_key": group_key,
                "label": label,
                "metric_key": metric_key,
                "value": row.get("metric_value_numeric"),
                "status": row.get("status"),
            }
        )

    if not parsed_rows:
        return pd.DataFrame()

    table: dict[object, dict] = {}
    for row in parsed_rows:
        item = table.setdefault(row["group_key"], {"Name": row["label"], "Status": "ok"})
        item[row["metric_key"]] = row["value"]
        if row["status"] == "warning":
            item["Status"] = "warning"
        elif row["status"] in {"down", "error"} and item["Status"] != "warning":
            item["Status"] = row["status"]
    return pd.DataFrame(table.values())


def _interface_view(dataframe: pd.DataFrame) -> pd.DataFrame:
    table = _dynamic_mikrotik_metric_table(dataframe, "interface")
    if table.empty:
        return table
    for column in ["rx_bytes", "tx_bytes", "rx_mbps", "tx_mbps"]:
        if column not in table.columns:
            table[column] = 0.0
    table = table[
        table[["rx_bytes", "tx_bytes", "rx_mbps", "tx_mbps"]]
        .fillna(0)
        .astype(float)
        .gt(0)
        .any(axis=1)
    ].copy()
    if table.empty:
        return table
    view = table[["Name", "rx_bytes", "tx_bytes", "rx_mbps", "tx_mbps", "Status"]].copy()
    view["RX Bytes"] = view["rx_bytes"].apply(_format_bytes)
    view["TX Bytes"] = view["tx_bytes"].apply(_format_bytes)
    view["RX Mbps"] = view["rx_mbps"].apply(_format_mbps)
    view["TX Mbps"] = view["tx_mbps"].apply(_format_mbps)
    return view[["Name", "RX Bytes", "TX Bytes", "RX Mbps", "TX Mbps", "Status"]].rename(columns={"Name": "Interface"})


def _firewall_view(dataframe: pd.DataFrame) -> pd.DataFrame:
    table = _dynamic_mikrotik_metric_table(dataframe, "firewall")
    if table.empty:
        return table
    for column in ["packets", "bytes", "pps", "mbps"]:
        if column not in table.columns:
            table[column] = 0.0
    table = table.sort_values(["pps", "mbps", "packets"], ascending=False).head(12)
    view = table[["Name", "packets", "bytes", "pps", "mbps", "Status"]].copy()
    view["Packets"] = view["packets"].fillna(0).astype(int).map(lambda value: f"{value:,}")
    view["Bytes"] = view["bytes"].apply(_format_bytes)
    view["PPS"] = view["pps"].apply(lambda value: f"{float(value or 0):.1f}")
    view["Mbps"] = view["mbps"].apply(_format_mbps)
    view["Spike"] = view["Status"].map(lambda status: "Possible spike" if status == "warning" else "-")
    return view[["Name", "Packets", "Bytes", "PPS", "Mbps", "Spike"]].rename(columns={"Name": "Rule"})


def _render_mikrotik_history_section(mikrotik_history_frame: pd.DataFrame) -> None:
    if mikrotik_history_frame.empty:
        st.info("Belum ada metrik Mikrotik API. Pastikan device aktif dan monitoring cycle berjalan.")
        return

    latest_map = _latest_metric_snapshot_map(mikrotik_history_frame)
    interface_frame = _interface_view(mikrotik_history_frame)
    firewall_frame = _firewall_view(mikrotik_history_frame)

    st.markdown("### Metrik Mikrotik")
    health_col1, health_col2, health_col3, health_col4, health_col5 = st.columns(5)
    _render_stat_card(health_col1, "CPU Load", _format_percent(_latest_metric_value_from_map(latest_map, "cpu_percent")))
    _render_stat_card(
        health_col2,
        "Memory Used",
        _format_percent(_latest_metric_value_from_map(latest_map, "memory_percent")),
    )
    _render_stat_card(
        health_col3,
        "Storage Used",
        _format_percent(_latest_metric_value_from_map(latest_map, "disk_percent")),
    )
    _render_stat_card(health_col4, "DHCP Leases", _latest_metric_value_from_map(latest_map, "dhcp_active_leases"))
    _render_stat_card(health_col5, "Connected Clients", _latest_metric_value_from_map(latest_map, "connected_clients"))

    st.markdown("### Interface Traffic")
    if interface_frame.empty:
        st.info("Belum ada data interface traffic. Coba perluas rentang waktu atau cek status API Mikrotik.")
    else:
        chart_frame = interface_frame.copy()
        chart_frame["RX Mbps"] = pd.to_numeric(chart_frame["RX Mbps"], errors="coerce").fillna(0)
        chart_frame["TX Mbps"] = pd.to_numeric(chart_frame["TX Mbps"], errors="coerce").fillna(0)
        traffic_chart_col, traffic_table_col = st.columns([1, 2])
        with traffic_chart_col:
            melted = chart_frame.melt(
                id_vars=["Interface"],
                value_vars=["RX Mbps", "TX Mbps"],
                var_name="Direction",
                value_name="Mbps",
            )
            traffic_chart = (
                alt.Chart(melted)
                .mark_bar()
                .encode(
                    x=alt.X("Mbps:Q", title="Mbps"),
                    y=alt.Y("Interface:N", sort="-x", title="Interface"),
                    color=alt.Color("Direction:N", title="Direction"),
                    tooltip=[
                        alt.Tooltip("Interface:N", title="Interface"),
                        alt.Tooltip("Direction:N", title="Direction"),
                        alt.Tooltip("Mbps:Q", title="Mbps", format=".2f"),
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(traffic_chart, width="stretch")
        with traffic_table_col:
            st.dataframe(
                interface_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "Interface": st.column_config.TextColumn("Interface", width="medium"),
                    "RX Bytes": st.column_config.TextColumn("RX Bytes", width="small"),
                    "TX Bytes": st.column_config.TextColumn("TX Bytes", width="small"),
                    "RX Mbps": st.column_config.TextColumn("RX Mbps", width="small"),
                    "TX Mbps": st.column_config.TextColumn("TX Mbps", width="small"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                },
            )

    st.markdown("### Firewall / NAT Counters")
    if firewall_frame.empty:
        st.info("Belum ada counter firewall/NAT. Pastikan metrik firewall diambil pada siklus monitoring.")
    else:
        st.dataframe(
            firewall_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "Rule": st.column_config.TextColumn("Rule", width="large"),
                "Packets": st.column_config.TextColumn("Packets", width="small"),
                "Bytes": st.column_config.TextColumn("Bytes", width="small"),
                "PPS": st.column_config.TextColumn("PPS", width="small"),
                "Mbps": st.column_config.TextColumn("Mbps", width="small"),
                "Spike": st.column_config.TextColumn("Spike", width="small"),
            },
        )


def _is_dynamic_mikrotik_metric(metric_name: str) -> bool:
    return str(metric_name or "").startswith(("interface:", "queue:", "firewall:"))


def _default_mikrotik_trend_metrics(metric_names: list[str]) -> list[str]:
    preferred_metrics = [
        "ping",
        "packet_loss",
        "jitter",
        "cpu_percent",
    ]
    available = set(str(metric_name) for metric_name in metric_names)
    return [metric_name for metric_name in preferred_metrics if metric_name in available]


def _render_printer_history_section(
    printer_history_frame: pd.DataFrame,
) -> None:
    if printer_history_frame.empty:
        st.info("Belum ada metrik printer SNMP. Periksa koneksi SNMP printer dan jalankan monitoring cycle.")
        return

    latest_map = _latest_metric_snapshot_map(printer_history_frame)
    status_row = latest_map.get("printer_status")
    error_row = latest_map.get("printer_error_state")
    ink_status_row = latest_map.get("printer_ink_status")
    paper_row = latest_map.get("printer_paper_status")
    uptime_row = latest_map.get("printer_uptime_seconds")
    pages_row = latest_map.get("printer_total_pages")
    st.markdown("### Kesehatan Printer")
    st.caption("Ringkasan status printer, deteksi gangguan, uptime, dan counter halaman.")
    status_columns = st.columns(6)
    status_cards = [
        (
            "Status Keseluruhan",
            str(status_row["display_value"]) if status_row is not None else "-",
            f"Status metrik: {str(status_row['status']).upper()}" if status_row is not None else "",
        ),
        (
            "Status Error",
            str(error_row["display_value"]) if error_row is not None else "-",
            f"Tingkat: {str(error_row['status']).upper()}" if error_row is not None else "",
        ),
        (
            "Status Kertas",
            str(paper_row["display_value"]) if paper_row is not None else "-",
            f"Status metrik: {str(paper_row['status']).upper()}" if paper_row is not None else "",
        ),
        (
            "Status Tinta",
            str(ink_status_row["display_value"]) if ink_status_row is not None else "-",
            "Status consumable keseluruhan dari printer",
        ),
        (
            "Uptime",
            str(uptime_row["display_value"]) if uptime_row is not None else "-",
            "Dipakai untuk deteksi reboot",
        ),
        (
            "Total Halaman",
            str(pages_row["display_value"]) if pages_row is not None else "-",
            "Counter akumulatif printer",
        ),
    ]
    for column, (label, value, meta) in zip(status_columns, status_cards, strict=False):
        with column.container(border=True):
            st.metric(label, value)
            if meta:
                st.caption(meta)


__all__ = [name for name in globals() if not name.startswith("__")]

