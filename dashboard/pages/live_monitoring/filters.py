"""Live Monitoring filter controls."""

from datetime import date
from typing import Any

import streamlit as st

try:
    from components.api import get_json
    from components.ui import normalize_status_label
except ModuleNotFoundError:  # pragma: no cover - supports imports outside Streamlit's app root
    from dashboard.components.api import get_json
    from dashboard.components.ui import normalize_status_label

from dashboard.pages.live_monitoring.helpers import (
    CHART_WINDOW_OPTIONS,
    INTERNET_ONLY_METRICS,
    STATUS_OPTIONS,
    _default_device_option_label,
    _filter_metric_names,
    _metric_filter_label,
    is_mikrotik_device,
)


def render_history_filters(
    *,
    devices: list[dict],
    device_options: dict[str, int | None],
    device_by_id: dict[int, dict],
    voip_group_label: str | None,
    voip_device_ids: list[int],
    today: date,
    default_start_date: date,
    auto_refresh: bool,
) -> dict[str, Any]:
    """Render history filters for the dashboard UI."""
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
    selected_is_voip_group = selected_device == voip_group_label
    selected_device_record = device_by_id.get(int(selected_device_id)) if selected_device_id is not None else None
    selected_device_type = "voip" if selected_is_voip_group else (str(selected_device_record.get("device_type")) if selected_device_record else None)
    status_value = filter_col3.selectbox(
        "Status",
        options=STATUS_OPTIONS,
        index=0,
        format_func=lambda value: "Semua" if value == "All" else normalize_status_label(str(value)),
    )
    metric_names_path = "/metrics/names"
    if selected_device_id is not None:
        metric_names_path = f"/metrics/names?device_id={selected_device_id}"
    elif selected_is_voip_group and voip_device_ids:
        # A representative VoIP keeps the group metric picker focused on metrics
        # that the group actually collects, rather than every device type's metric.
        metric_names_path = f"/metrics/names?device_id={voip_device_ids[0]}"
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
            checked_from_date = default_start_date
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
        "selected_is_device_group": selected_is_voip_group,
        "selected_group_device_ids": voip_device_ids if selected_is_voip_group else [],
        "status_value": status_value,
        "selected_metric": selected_metric,
        "metric_name_options": metric_name_options,
    }
