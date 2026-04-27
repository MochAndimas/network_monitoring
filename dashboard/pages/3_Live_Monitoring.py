"""Define module logic for `dashboard/pages/3_Live_Monitoring.py`.

This module contains project-specific implementation details.
"""

from datetime import datetime, timedelta
from typing import Any, cast

import streamlit as st

from shared.device_utils import format_device_label
from components.auth import require_dashboard_login
from components.api import get_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.ui import render_meta_row, render_page_header
from dashboard.pages.live_monitoring.helpers import (
    CHART_WINDOW_OPTIONS,
    INTERNET_ONLY_METRICS,
    PRINTER_METRIC_NAMES,
    STATUS_OPTIONS,
    _default_device_option_label,
    _default_mikrotik_trend_metrics,
    _entity_volume_frame,
    _fetch_device_history_rows,
    _fetch_latest_device_snapshot,
    _filter_history_rows,
    _filter_metric_names,
    _format_duration,
    _format_metric_numeric,
    _friendly_metric_name,
    _health_score_percent,
    _is_dynamic_mikrotik_metric,
    _latest_snapshot_frame,
    _metric_filter_label,
    _metric_kpi_summary,
    _non_numeric_metric_timeline,
    _paginate_frame,
    _prepare_history_frame,
    _raw_history_view,
    _recent_anomaly_frame,
    _render_metric_trend_section,
    _render_mikrotik_history_section,
    _render_printer_history_section,
    _render_stat_card,
    _should_hide_metric_for_device,
    _snapshot_pagination_controls,
    _status_color_scale,
    _status_counts_frame,
    _status_label_for_display,
    _trend_direction_text,
    alt,
    format_wib_timestamp,
    is_mikrotik_device,
    normalize_status_label,
    paged_items,
    paged_meta,
    pd,
    urlencode,
    wib_date_boundary_to_utc_iso,
)

st.set_page_config(page_title="Live Monitoring", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()

render_page_header(
    "Live Monitoring",
    "Monitoring metrik live untuk analisis tren dan investigasi insiden.",
)

devices = get_json("/devices/options?active_only=false&limit=300&offset=0", [])
device_type_by_id = {
    int(device["id"]): str(device.get("device_type") or "")
    for device in devices
}
device_name_by_id = {
    int(device["id"]): str(device.get("name") or "")
    for device in devices
}
device_by_id = {
    int(device["id"]): device
    for device in devices
}
device_options = {"Semua Device": None}
for device in devices:
    device_options[format_device_label(device)] = device["id"]

today = datetime.now().date()
default_start_date = today - timedelta(days=1)
auto_refresh, interval_seconds = refresh_controls("history", default_enabled=True, default_interval=15)


def _render_history_filters() -> dict:
    """Render history filters.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    default_device_label = _default_device_option_label(devices)
    device_option_labels = list(device_options.keys())
    if "history_selected_device" not in st.session_state or st.session_state["history_selected_device"] not in device_option_labels:
        fallback_device = default_device_label if default_device_label in device_option_labels else device_option_labels[0]
        st.session_state["history_selected_device"] = fallback_device
    if (
        "history_chart_window" not in st.session_state
        or st.session_state["history_chart_window"] not in CHART_WINDOW_OPTIONS
    ):
        st.session_state["history_chart_window"] = "1 jam"

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    selected_device = filter_col1.selectbox(
        "Device",
        options=device_option_labels,
        key="history_selected_device",
    )
    selected_device_id = device_options[selected_device]
    selected_device_record = device_by_id.get(int(selected_device_id)) if selected_device_id is not None else None
    selected_device_type = str(selected_device_record.get("device_type")) if selected_device_record else None
    status_value = filter_col3.selectbox(
        "Status",
        options=STATUS_OPTIONS,
        index=0,
        format_func=lambda value: "Semua" if value == "All" else normalize_status_label(str(value)),
    )
    metric_names_path = "/metrics/names"
    if selected_device_id is not None:
        metric_names_path = f"/metrics/names?device_id={selected_device_id}"
    metric_name_options = _filter_metric_names(
        get_json(metric_names_path, []),
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    if (
        is_mikrotik_device(
            selected_device_type,
            selected_device_record.get("name") if selected_device_record else None,
        )
        and st.session_state.get("history_selected_metric") in INTERNET_ONLY_METRICS
    ):
        st.session_state["history_selected_metric"] = "All Metrics"
    metric_select_options = ["All Metrics"] + metric_name_options
    if st.session_state.get("history_selected_metric") not in metric_select_options:
        st.session_state["history_selected_metric"] = "All Metrics"
    metric_filter_labels = {
        metric_name: _metric_filter_label(metric_name)
        for metric_name in metric_select_options
    }
    selected_metric = filter_col2.selectbox(
        "Nama Metrik",
        options=metric_select_options,
        index=0,
        format_func=lambda metric_name: metric_filter_labels.get(metric_name, str(metric_name)),
        help="Daftar metrik yang sudah tersimpan di history.",
        key="history_selected_metric",
    )
    with st.expander("Filter Lanjutan"):
        advanced_col1, advanced_col2, advanced_col3, advanced_col4 = st.columns(4)
        limit_value = advanced_col1.selectbox("Baris", options=[50, 100, 200, 300, 500], index=2)
        chart_window_label = advanced_col2.selectbox(
            "Rentang Chart",
            options=list(CHART_WINDOW_OPTIONS.keys()),
            help="Pilih rentang waktu yang dipakai untuk chart tren.",
            key="history_chart_window",
        )
        if auto_refresh:
            checked_from_date = today - timedelta(days=1)
            checked_to_date = today
            advanced_col3.date_input("Dicek Dari", value=checked_from_date, disabled=True)
            advanced_col4.date_input("Dicek Sampai", value=checked_to_date, disabled=True)
            st.caption("Live mode mengunci rentang ke 24 jam terakhir.")
        else:
            checked_from_date = advanced_col3.date_input("Dicek Dari", value=default_start_date)
            checked_to_date = advanced_col4.date_input("Dicek Sampai", value=today)
    return {
        "limit_value": limit_value,
        "chart_window_label": chart_window_label,
        "checked_from_date": checked_from_date,
        "checked_to_date": checked_to_date,
        "selected_device": selected_device,
        "selected_device_id": selected_device_id,
        "selected_device_record": selected_device_record,
        "selected_device_type": selected_device_type,
        "status_value": status_value,
        "selected_metric": selected_metric,
    }


history_filters = _render_history_filters()


def _render_history_body() -> None:
    """Render history body.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    meta_container = st.container()
    summary_container = st.container()
    snapshot_container = st.container()
    status_container = st.container()
    prepared_history_frame_cache: dict[tuple[int, bool], pd.DataFrame] = {}

    def _prepare_history_frame_cached(rows: list[dict], *, sort_desc: bool = True) -> pd.DataFrame:
        key = (id(rows), sort_desc)
        cached = prepared_history_frame_cache.get(key)
        if cached is not None:
            return cached
        prepared = _prepare_history_frame(rows, sort_desc=sort_desc)
        prepared_history_frame_cache[key] = prepared
        return prepared

    limit_value = int(history_filters["limit_value"])
    chart_window_label = str(history_filters["chart_window_label"])
    checked_from_date = history_filters["checked_from_date"]
    checked_to_date = history_filters["checked_to_date"]
    selected_device = str(history_filters["selected_device"])
    selected_device_id = history_filters["selected_device_id"]
    selected_device_record = history_filters["selected_device_record"]
    selected_device_type = history_filters["selected_device_type"]
    status_value = str(history_filters["status_value"])
    selected_metric = str(history_filters["selected_metric"])

    snapshot_page_size = int(st.session_state.get("history_snapshot_page_size", 10))
    snapshot_page = int(st.session_state.get("history_snapshot_page", 1))
    snapshot_offset = (snapshot_page - 1) * snapshot_page_size
    context_query_params: dict[str, Any] = {
        "limit": limit_value,
        "selected_device_limit": limit_value,
        "snapshot_limit": snapshot_page_size,
        "snapshot_offset": snapshot_offset,
    }
    if selected_device_id is not None:
        context_query_params["device_id"] = selected_device_id
    if selected_device_id is not None and is_mikrotik_device(
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    ):
        context_query_params["include_selected_device_snapshot"] = "true"
    if selected_metric != "All Metrics" and not _should_hide_metric_for_device(
        selected_metric,
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    ):
        context_query_params["metric_name"] = selected_metric
    if checked_from_date:
        context_query_params["checked_from"] = wib_date_boundary_to_utc_iso(checked_from_date)
    if checked_to_date:
        context_query_params["checked_to"] = wib_date_boundary_to_utc_iso(checked_to_date, end_of_day=True)
    if status_value != "All":
        context_query_params["status"] = status_value
    history_context_endpoint = "/metrics/history/live" if auto_refresh else "/metrics/history/context"
    history_context = get_json(
        f"{history_context_endpoint}?{urlencode(context_query_params)}",
        {
            "metric_names": [],
            "history": {"items": [], "meta": {}},
            "selected_device_history": {"items": [], "meta": {}},
            "latest_snapshot": {"items": [], "meta": {}},
            "selected_device_snapshot": {"items": [], "meta": {}},
            "latest_snapshot_status_summary": {},
            "snapshot_uptime_map": {},
        },
    )
    metric_name_options = _filter_metric_names(
        history_context.get("metric_names", []),
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    if selected_metric != "All Metrics" and selected_metric not in metric_name_options:
        selected_metric = "All Metrics"
    history_payload = history_context.get("history", {"items": [], "meta": {}})
    selected_device_history_payload = history_context.get("selected_device_history", {"items": [], "meta": {}})
    selected_device_history_raw = paged_items(selected_device_history_payload)
    history = paged_items(history_payload)
    history_meta = paged_meta(history_payload)
    history = _filter_history_rows(history, device_type_by_id, device_name_by_id)
    selected_device_history = _filter_history_rows(selected_device_history_raw, device_type_by_id, device_name_by_id)
    selected_is_mikrotik = selected_device_id is not None and is_mikrotik_device(
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    full_device_history = selected_device_history
    if selected_device_id is not None and auto_refresh:
        if selected_metric == "All Metrics":
            live_metric_names = metric_name_options
            if selected_is_mikrotik:
                live_metric_names = _default_mikrotik_trend_metrics(metric_name_options)
            if not live_metric_names:
                live_metric_names = metric_name_options
            full_device_history = _filter_history_rows(
                _fetch_device_history_rows(
                    device_id=selected_device_id,
                    checked_from_date=checked_from_date,
                    checked_to_date=checked_to_date,
                    metric_names=live_metric_names,
                    status=status_value,
                    max_pages=1,
                ),
                device_type_by_id,
                device_name_by_id,
            )
        elif selected_metric != "All Metrics":
            full_device_history = _filter_history_rows(
                _fetch_device_history_rows(
                    device_id=selected_device_id,
                    checked_from_date=checked_from_date,
                    checked_to_date=checked_to_date,
                    metric_names=[selected_metric],
                    status=status_value,
                    max_pages=1,
                ),
                device_type_by_id,
                device_name_by_id,
            )
        else:
            full_device_history = selected_device_history
    elif selected_device_id is not None:
        if selected_is_mikrotik and selected_metric == "All Metrics":
            metric_names: list[str] | None = _default_mikrotik_trend_metrics(metric_name_options)
            max_history_pages = 1
            initial_history_payload = None
        else:
            metric_names = None if selected_metric == "All Metrics" else [selected_metric]
            max_history_pages = None
            initial_history_payload = selected_device_history_payload
        full_device_history = _filter_history_rows(
            _fetch_device_history_rows(
                device_id=selected_device_id,
                checked_from_date=checked_from_date,
                checked_to_date=checked_to_date,
                metric_names=metric_names,
                status=status_value,
                max_pages=max_history_pages,
                initial_payload=initial_history_payload,
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
        render_meta_row(
            [
                ("Refresh Otomatis", live_status_text(auto_refresh, interval_seconds)),
                ("Terakhir Diperbarui", rendered_at_label()),
                ("Device", selected_device),
                ("Rentang", "24 jam terakhir (live)" if auto_refresh else f"{checked_from_date} s/d {checked_to_date}"),
                ("Jendela Grafik", chart_window_label),
                ("Sampel Live" if auto_refresh else "Total Data Sesuai", int(history_meta.get("total", 0) or 0)),
            ]
        )

    if not history:
        st.info("Belum ada histori metrik untuk filter ini. Ubah rentang waktu atau jalankan monitoring cycle.")
        return

    dataframe = _prepare_history_frame_cached(history)
    if dataframe.empty:
        st.info("Belum ada histori metrik untuk filter ini. Ubah rentang waktu atau jalankan monitoring cycle.")
        return

    snapshot_frame = _prepare_history_frame_cached(snapshot_history, sort_desc=False)
    latest_per_series = snapshot_frame.copy() if not snapshot_frame.empty else _latest_snapshot_frame(dataframe)
    uptime_keys = latest_per_series["device_id"].astype(int).astype(str) + ":" + latest_per_series["metric_name"].astype(str)
    uptime_values = uptime_keys.map(snapshot_uptime_map).fillna("-").astype(str)
    latest_per_series["uptime"] = uptime_values.map(
        lambda value: _format_duration(pd.Timedelta(seconds=float(value))) if value not in {"", "-"} else "-"
    )
    summary_rows = full_device_history if selected_device_id is not None else history
    summary_frame = _prepare_history_frame_cached(summary_rows, sort_desc=False)
    if summary_frame.empty:
        summary_frame = dataframe
    summary_latest_timestamp = summary_frame["checked_at"].max()
    if selected_device_id is not None:
        summary_latest_per_series = _latest_snapshot_frame(summary_frame)
    else:
        summary_latest_per_series = latest_per_series
    metric_insight_snapshot = summary_latest_per_series
    if selected_metric != "All Metrics":
        metric_insight_snapshot = summary_latest_per_series[
            summary_latest_per_series["metric_name"].astype(str) == str(selected_metric)
        ].copy()
    status_counts = _status_counts_frame(
        latest_snapshot_status_summary if selected_metric == "All Metrics" and selected_device_id is None else {},
        metric_insight_snapshot,
    )
    health_score = _health_score_percent(status_counts)
    anomaly_count = (
        int(status_counts[status_counts["status"].isin(["Warning", "Down", "Error"])]["Jumlah"].sum())
        if not status_counts.empty
        else 0
    )

    with summary_container:
        st.markdown("### Ringkasan Eksekutif")
        if selected_device_id is not None:
            st.caption(f"Ringkasan cepat untuk device terpilih: {selected_device}.")
        else:
            st.caption("Ringkasan cepat untuk melihat kondisi keseluruhan sebelum masuk ke investigasi detail.")
        summary_col1, summary_col2, summary_col3, summary_col4, summary_col5 = st.columns(5)
        _render_stat_card(summary_col1, "Total Data", int(len(summary_frame)))
        _render_stat_card(summary_col2, "Device Terpantau", int(summary_frame["device_name"].nunique()))
        _render_stat_card(summary_col3, "Metrik Aktif", int(summary_frame["metric_name"].nunique()))
        _render_stat_card(summary_col4, "Anomali Aktif", anomaly_count)
        _render_stat_card(summary_col5, "Skor Kesehatan", f"{health_score}%")
        st.caption(f"Pengecekan terakhir pada {format_wib_timestamp(summary_latest_timestamp)} WIB.")

    with snapshot_container:
        st.markdown("### Snapshot Terbaru")
        st.caption(
            f"Menampilkan {len(latest_per_series)} dari total {snapshot_meta.get('total', len(latest_per_series))} metrik terakhir."
        )
        snapshot_view = latest_per_series[
            ["device_name", "metric_label", "display_value", "uptime", "status", "checked_at_wib"]
        ].rename(
            columns={
                "device_name": "Device",
                "metric_label": "Metrik",
                "display_value": "Nilai Terakhir",
                "uptime": "Uptime",
                "status": "Status",
                "checked_at_wib": "Dicek (WIB)",
            }
        )
        snapshot_view["Status"] = snapshot_view["Status"].map(_status_label_for_display)
        st.dataframe(
            snapshot_view,
            width="stretch",
            hide_index=True,
            column_config={
                "Device": st.column_config.TextColumn("Device", width="medium"),
                "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                "Nilai Terakhir": st.column_config.TextColumn("Nilai Terakhir", width="small"),
                "Uptime": st.column_config.TextColumn("Uptime", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
            },
        )
        _snapshot_pagination_controls(int(snapshot_meta.get("total", len(latest_per_series))))

    with status_container:
        st.markdown("### Insight Analisis")
        insight_base_frame = dataframe.copy()
        if selected_metric != "All Metrics":
            insight_base_frame = insight_base_frame[
                insight_base_frame["metric_name"].astype(str) == str(selected_metric)
            ].copy()
            st.caption(f"Insight difokuskan untuk metrik `{_friendly_metric_name(selected_metric)}`.")
        insight_col1, insight_col2 = st.columns([2, 1])
        if status_counts.empty:
            insight_col1.info("Belum ada status device untuk diringkas pada rentang ini.")
        else:
            status_chart = (
                alt.Chart(status_counts)
                .mark_arc(innerRadius=55)
                .encode(
                    theta=alt.Theta("Jumlah:Q", title="Jumlah"),
                    color=alt.Color("status:N", title="Status", scale=_status_color_scale()),
                    tooltip=[
                        alt.Tooltip("status:N", title="Status"),
                        alt.Tooltip("Jumlah:Q", title="Jumlah"),
                    ],
                    order=alt.Order("priority:Q", sort="ascending"),
                )
                .properties(height=260)
            )
            insight_col1.altair_chart(status_chart, width="stretch")

        with insight_col2:
            if not status_counts.empty:
                status_view = status_counts[["status", "Jumlah"]].copy()
                status_view["Status"] = status_view["status"].map(_status_label_for_display)
                status_view = status_view[["Status", "Jumlah"]]
            else:
                status_view = pd.DataFrame(columns=["Status", "Jumlah"])
            st.dataframe(
                status_view,
                width="stretch",
                hide_index=True,
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
                },
            )

        top_device_frame = _entity_volume_frame(insight_base_frame, "device_name", "Device", top_n=6)
        top_col1, top_col2 = st.columns(2)
        top_col1.markdown("#### Device Paling Aktif")
        top_col1.dataframe(
            top_device_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "Device": st.column_config.TextColumn("Device", width="medium"),
                "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
            },
        )
        if selected_metric != "All Metrics":
            top_status_frame = (
                insight_base_frame["status"]
                .map(_status_label_for_display)
                .value_counts()
                .head(6)
                .rename_axis("Status")
                .reset_index(name="Jumlah")
                if not insight_base_frame.empty
                else pd.DataFrame(columns=["Status", "Jumlah"])
            )
            top_col2.markdown("#### Status Terbanyak")
            top_col2.dataframe(
                top_status_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="medium"),
                    "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
                },
            )
        else:
            top_metric_frame = _entity_volume_frame(insight_base_frame, "metric_label", "Metrik", top_n=6)
            top_col2.markdown("#### Metrik Paling Sering Muncul")
            top_col2.dataframe(
                top_metric_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                    "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
                },
            )

        anomaly_frame = _recent_anomaly_frame(insight_base_frame)
        if not anomaly_frame.empty:
            st.markdown("#### Anomali Terbaru")
            anomaly_view = anomaly_frame[
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
            anomaly_view["Status"] = anomaly_view["Status"].map(_status_label_for_display)
            st.dataframe(
                anomaly_view,
                width="stretch",
                hide_index=True,
                column_config={
                    "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
                    "Device": st.column_config.TextColumn("Device", width="medium"),
                    "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                    "Nilai": st.column_config.TextColumn("Nilai", width="small"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                },
            )

    if selected_is_mikrotik:
        selected_device_snapshot_payload = history_context.get("selected_device_snapshot", {"items": [], "meta": {}})
        mikrotik_snapshot = _filter_history_rows(
            paged_items(selected_device_snapshot_payload),
            device_type_by_id,
            device_name_by_id,
        )
        if not mikrotik_snapshot:
            mikrotik_snapshot = _filter_history_rows(
                _fetch_latest_device_snapshot(selected_device_id),
                device_type_by_id,
                device_name_by_id,
            )
        mikrotik_history_frame = _prepare_history_frame_cached(mikrotik_snapshot, sort_desc=False)
        _render_mikrotik_history_section(mikrotik_history_frame)

    if selected_device_id is not None and selected_device_type == "printer":
        printer_history = [
            row for row in selected_device_history if str(row.get("metric_name") or "") in PRINTER_METRIC_NAMES
        ]
        printer_history_frame = _prepare_history_frame_cached(printer_history, sort_desc=False)
        _render_printer_history_section(printer_history_frame)

    st.markdown("### Tren Metrik")
    if selected_device_id is None:
        st.info("Pilih satu device untuk menampilkan grafik tren.")
        return

    device_history_frame = _prepare_history_frame_cached(full_device_history, sort_desc=False)
    if device_history_frame.empty:
        st.info("Belum ada history lengkap untuk device ini pada rentang waktu terpilih.")
        return
    dataframe_desc = dataframe.sort_values("checked_at", ascending=False).copy()
    device_history_frame_desc = device_history_frame.sort_values("checked_at", ascending=False).copy()

    available_metric_names = sorted(device_history_frame["metric_name"].dropna().unique().tolist())
    if selected_is_mikrotik and selected_metric == "All Metrics":
        metric_names_to_render = _default_mikrotik_trend_metrics(available_metric_names)
    else:
        metric_names_to_render = [selected_metric] if selected_metric != "All Metrics" else available_metric_names
    metric_names_to_render = _filter_metric_names(
        metric_names_to_render,
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    if selected_is_mikrotik and selected_metric == "All Metrics":
        metric_names_to_render = [
            metric_name for metric_name in metric_names_to_render if not _is_dynamic_mikrotik_metric(metric_name)
        ]
    if selected_metric != "All Metrics":
        selected_metric_frame = device_history_frame[
            device_history_frame["metric_name"].astype(str) == str(selected_metric)
        ].copy()
    else:
        selected_metric_frame = pd.DataFrame()
    rendered_metric_frames: list[pd.DataFrame] = []
    metric_frame_by_name = {
        str(metric_name): metric_frame
        for metric_name, metric_frame in device_history_frame.groupby(device_history_frame["metric_name"].astype(str))
    }
    for metric_name in metric_names_to_render:
        metric_series_frame = metric_frame_by_name.get(str(metric_name))
        if metric_series_frame is None:
            continue
        metric_series_frame = metric_series_frame.dropna(subset=["metric_value_numeric"]).sort_values("checked_at").copy()
        if metric_series_frame.empty:
            continue
        rendered_metric_frames.append(metric_series_frame)

    if not rendered_metric_frames:
        if selected_metric != "All Metrics" and not selected_metric_frame.empty:
            st.info("Metrik ini tidak punya nilai numerik. Menampilkan timeline status dan nilai terbaru.")
            st.markdown("#### Timeline Nilai Non-Numerik")
            non_numeric_timeline = _non_numeric_metric_timeline(selected_metric_frame)
            st.dataframe(
                non_numeric_timeline,
                width="stretch",
                hide_index=True,
                column_config={
                    "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
                    "Nilai": st.column_config.TextColumn("Nilai", width="medium"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Device": st.column_config.TextColumn("Device", width="medium"),
                    "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                },
            )
            return
        st.info("Belum ada data numerik untuk kombinasi device dan metrik ini.")
        return

    if selected_metric != "All Metrics" and rendered_metric_frames:
        selected_metric_summary = _metric_kpi_summary(rendered_metric_frames[0])
        if selected_metric_summary:
            st.markdown("#### Ringkasan Metrik Terpilih")
            st.caption(
                f"{selected_metric_summary['metric_label']} pada {selected_metric_summary['device_name']} - "
                f"{selected_metric_summary['count']} sampel pada rentang terpilih."
            )
            selected_col1, selected_col2, selected_col3, selected_col4, selected_col5, selected_col6 = st.columns(6)
            _render_stat_card(selected_col1, "Nilai Terakhir", str(selected_metric_summary["latest_display"]))
            _render_stat_card(
                selected_col2,
                "Arah Tren",
                _trend_direction_text(cast(float | None, selected_metric_summary.get("delta"))),
            )
            _render_stat_card(
                selected_col3,
                "Rata-rata",
                _format_metric_numeric(
                    cast(float | int | None, selected_metric_summary.get("avg")),
                    str(selected_metric_summary.get("unit") or ""),
                ),
            )
            _render_stat_card(
                selected_col4,
                "Minimum",
                _format_metric_numeric(
                    cast(float | int | None, selected_metric_summary.get("min")),
                    str(selected_metric_summary.get("unit") or ""),
                ),
            )
            _render_stat_card(
                selected_col5,
                "Maksimum",
                _format_metric_numeric(
                    cast(float | int | None, selected_metric_summary.get("max")),
                    str(selected_metric_summary.get("unit") or ""),
                ),
            )
            _render_stat_card(selected_col6, "Status Terakhir", str(selected_metric_summary["status"]))

    chart_rows = [rendered_metric_frames[i:i + 1] for i in range(0, len(rendered_metric_frames), 1)]
    for row_frames in chart_rows:
        chart_columns = st.columns(1)
        for col_index, metric_frame in enumerate(row_frames):
            _render_metric_trend_section(
                metric_frame,
                chart_window_label=chart_window_label,
                target_column=chart_columns[col_index],
            )

    st.markdown("### Riwayat Detail")
    if selected_device_id is not None and selected_device_type == "printer":
        raw_history_frame = device_history_frame_desc if not device_history_frame.empty else dataframe_desc
    elif selected_is_mikrotik and selected_metric == "All Metrics":
        raw_history_frame = dataframe_desc
    else:
        raw_history_frame = pd.concat(rendered_metric_frames, ignore_index=True).sort_values("checked_at", ascending=False)
    raw_view = _raw_history_view(raw_history_frame, metric_selected=selected_metric != "All Metrics")
    if "Status" in raw_view.columns:
        raw_view["Status"] = raw_view["Status"].map(_status_label_for_display)
    paged_raw_view = _paginate_frame(raw_view, key_prefix="history_raw", page_size=10)
    st.dataframe(
        paged_raw_view,
        width="stretch",
        hide_index=True,
        column_config={
            "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
            "Nilai": st.column_config.TextColumn("Nilai", width="small"),
            "Nilai Numerik": st.column_config.TextColumn("Nilai Numerik", width="small"),
            "Perubahan": st.column_config.TextColumn("Perubahan", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Device": st.column_config.TextColumn("Device", width="medium"),
            "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
            "Catatan": st.column_config.TextColumn("Catatan", width="small"),
        },
    )


render_live_section(auto_refresh, interval_seconds, _render_history_body)
