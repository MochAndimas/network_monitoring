"""Live Monitoring page body rendering."""

from typing import Any

import streamlit as st

try:
    from components.api import get_json
    from components.refresh import live_status_text, rendered_at_label
    from components.ui import render_meta_row
except ModuleNotFoundError:  # pragma: no cover - supports imports outside Streamlit's app root
    from dashboard.components.api import get_json
    from dashboard.components.refresh import live_status_text, rendered_at_label
    from dashboard.components.ui import render_meta_row

from dashboard.pages.live_monitoring.body_sections import render_device_detail_sections, render_history_overview_sections
from dashboard.pages.live_monitoring.helpers import (
    CHART_WINDOW_OPTIONS,
    _default_mikrotik_trend_metrics,
    _default_nas_trend_metrics,
    _fetch_device_history_rows,
    _filter_history_rows,
    _filter_metric_names,
    _format_duration,
    _health_score_percent,
    _latest_snapshot_frame,
    _prepare_history_frame,
    _should_hide_metric_for_device,
    _status_counts_frame,
    is_mikrotik_device,
    paged_items,
    paged_meta,
    pd,
    urlencode,
    wib_date_boundary_to_utc_iso,
)

def render_history_body(
    *,
    history_filters: dict[str, Any],
    auto_refresh: bool,
    interval_seconds: int,
    device_type_by_id: dict[int, str],
    device_name_by_id: dict[int, str],
) -> None:
    """Render history body for the dashboard UI."""
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
    metric_name_options = list(history_filters.get("metric_name_options", []))

    snapshot_page_size = int(st.session_state.get("history_snapshot_page_size", 10))
    snapshot_page = int(st.session_state.get("history_snapshot_page", 1))
    snapshot_offset = (snapshot_page - 1) * snapshot_page_size
    selected_is_mikrotik = selected_device_id is not None and is_mikrotik_device(
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    trend_metric_names = _selected_trend_metric_names(
        selected_metric=selected_metric,
        selected_device_type=selected_device_type,
        selected_is_mikrotik=selected_is_mikrotik,
        metric_name_options=metric_name_options,
    )
    trend_limit = _trend_limit_for_chart_window(limit_value, chart_window_label)
    context_query_params: dict[str, Any] = {
        "limit": limit_value,
        "selected_device_limit": limit_value,
        "snapshot_limit": snapshot_page_size,
        "snapshot_offset": snapshot_offset,
    }
    if selected_device_id is not None:
        context_query_params["device_id"] = selected_device_id
        context_query_params["include_selected_device_trend"] = "true"
        context_query_params["trend_limit"] = trend_limit
        if trend_metric_names:
            context_query_params["trend_metric_names"] = trend_metric_names
    if selected_is_mikrotik:
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
        _history_context_path(history_context_endpoint, context_query_params),
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
    selected_device_trend_payload = history_context.get("selected_device_trend", {"items": [], "meta": {}})
    selected_device_history_raw = paged_items(selected_device_history_payload)
    selected_device_trend_raw = paged_items(selected_device_trend_payload)
    history = paged_items(history_payload)
    history_meta = paged_meta(history_payload)
    history = _filter_history_rows(history, device_type_by_id, device_name_by_id)
    selected_device_history = _filter_history_rows(selected_device_history_raw, device_type_by_id, device_name_by_id)
    selected_device_trend = _filter_history_rows(
        selected_device_trend_raw,
        device_type_by_id,
        device_name_by_id,
    )
    full_device_history = selected_device_trend or selected_device_history
    if selected_device_id is not None and auto_refresh:
        if not selected_device_trend and selected_metric != "All Metrics":
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
    elif selected_device_id is not None:
        if selected_device_trend:
            full_device_history = selected_device_trend
        else:
            metric_names = None if selected_metric == "All Metrics" else [selected_metric]
            initial_history_payload = selected_device_history_payload
            full_device_history = _filter_history_rows(
                _fetch_device_history_rows(
                    device_id=selected_device_id,
                    checked_from_date=checked_from_date,
                    checked_to_date=checked_to_date,
                    metric_names=metric_names,
                    status=status_value,
                    max_pages=None,
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

    render_history_overview_sections(
        summary_container=summary_container,
        snapshot_container=snapshot_container,
        status_container=status_container,
        auto_refresh=auto_refresh,
        interval_seconds=interval_seconds,
        selected_device=selected_device,
        selected_device_id=selected_device_id,
        selected_metric=selected_metric,
        checked_from_date=checked_from_date,
        checked_to_date=checked_to_date,
        chart_window_label=chart_window_label,
        history_meta=history_meta,
        summary_frame=summary_frame,
        summary_latest_timestamp=summary_latest_timestamp,
        latest_per_series=latest_per_series,
        snapshot_meta=snapshot_meta,
        status_counts=status_counts,
        health_score=health_score,
        anomaly_count=anomaly_count,
        dataframe=dataframe,
    )

    render_device_detail_sections(
        history_context=history_context,
        device_type_by_id=device_type_by_id,
        device_name_by_id=device_name_by_id,
        selected_device_id=selected_device_id,
        selected_device_type=selected_device_type,
        selected_device_record=selected_device_record,
        selected_metric=selected_metric,
        selected_is_mikrotik=selected_is_mikrotik,
        selected_device_history=selected_device_history,
        full_device_history=full_device_history,
        checked_from_date=checked_from_date,
        checked_to_date=checked_to_date,
        status_value=status_value,
        chart_window_label=chart_window_label,
        dataframe=dataframe,
        prepare_history_frame=_prepare_history_frame_cached,
    )


def _selected_trend_metric_names(
    *,
    selected_metric: str,
    selected_device_type: str | None,
    selected_is_mikrotik: bool,
    metric_name_options: list[str],
) -> list[str]:
    """Return bounded trend metric names requested from the backend context endpoint."""
    if selected_metric != "All Metrics":
        return [selected_metric]
    if selected_is_mikrotik:
        return _default_mikrotik_trend_metrics(metric_name_options)
    if selected_device_type == "nas":
        return _default_nas_trend_metrics(metric_name_options)
    return metric_name_options


def _trend_limit_for_chart_window(limit_value: int, chart_window_label: str) -> int:
    """Return a per-metric trend row budget that can cover the selected chart window."""
    chart_window_hours = CHART_WINDOW_OPTIONS.get(chart_window_label, 1)
    estimated_minute_samples = int(chart_window_hours * 75)
    return min(max(limit_value, estimated_minute_samples), 2000)


def _history_context_path(endpoint: str, query_params: dict[str, Any]) -> str:
    """Build a context endpoint path, preserving repeated list query params."""
    return f"{endpoint}?{urlencode(query_params, doseq=True)}"
