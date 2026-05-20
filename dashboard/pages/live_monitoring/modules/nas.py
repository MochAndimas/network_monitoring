"""NAS-specific live monitoring helpers."""

import pandas as pd
import streamlit as st

from .constants import NAS_CARD_ONLY_METRIC_NAMES
from .data import _is_nas_card_only_metric
from .device_common import (
    _format_percent,
    _latest_metric_display_from_map,
    _latest_metric_snapshot_map,
    _latest_metric_value_from_map,
    _nas_volume_capacity_view,
)
from .formatting import _friendly_metric_name
from .rendering import _format_celsius, _render_stat_card, _status_label_for_display

def _render_nas_history_section(nas_history_frame: pd.DataFrame) -> None:
    """Render NAS health metrics as stable cards and compact status tables."""
    if nas_history_frame.empty:
        st.info("Belum ada metrik NAS SNMP. Periksa koneksi SNMP NAS dan jalankan monitoring cycle.")
        return

    latest_map = _latest_metric_snapshot_map(nas_history_frame)
    volume_capacity_frame = _nas_volume_capacity_view(latest_map)
    st.markdown("### Kesehatan NAS")
    health_columns = st.columns(6)
    health_cards = [
        ("CPU", _format_percent(_latest_metric_value_from_map(latest_map, "cpu_percent"))),
        ("Memory", _format_percent(_latest_metric_value_from_map(latest_map, "memory_percent"))),
        ("Volume Used", _format_percent(_latest_metric_value_from_map(latest_map, "disk_percent"))),
        ("System Temp", _format_celsius(_latest_metric_value_from_map(latest_map, "nas_system_temperature_c"))),
        ("System", _latest_metric_value_from_map(latest_map, "nas_system_status")),
        ("Uptime", _latest_metric_display_from_map(latest_map, "nas_uptime_seconds")),
    ]
    for column, (label, value) in zip(health_columns, health_cards, strict=False):
        _render_stat_card(column, label, str(value or "-"))

    status_rows = []
    temperature_rows = []
    for metric_name, row in sorted(latest_map.items()):
        metric_name = str(metric_name)
        if (
            _is_nas_card_only_metric(metric_name)
            and metric_name not in NAS_CARD_ONLY_METRIC_NAMES
            and metric_name.endswith(":status")
        ):
            status_rows.append(
                {
                    "Komponen": _friendly_metric_name(metric_name),
                    "Nilai": row.get("display_value"),
                    "Status": _status_label_for_display(row.get("status")),
                    "Dicek (WIB)": row.get("checked_at_wib"),
                }
            )
        if metric_name.startswith("nas_disk:") and metric_name.endswith(":temperature_c"):
            temperature_rows.append(
                {
                    "Disk": _friendly_metric_name(metric_name).replace("NAS Disk ", "").replace(" Temperature", ""),
                    "Temperature": row.get("display_value"),
                    "Status": _status_label_for_display(row.get("status")),
                    "Dicek (WIB)": row.get("checked_at_wib"),
                }
            )

    st.markdown("#### Kapasitas Volume")
    if volume_capacity_frame.empty:
        st.info("Belum ada detail kapasitas volume NAS.")
    else:
        st.dataframe(
            volume_capacity_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "Volume": st.column_config.TextColumn("Volume", width="medium"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Total": st.column_config.TextColumn("Total", width="small"),
                "Terpakai": st.column_config.TextColumn("Terpakai", width="small"),
                "Sisa": st.column_config.TextColumn("Sisa", width="small"),
                "Used": st.column_config.TextColumn("Used", width="small"),
                "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
            },
        )

    status_col, temp_col = st.columns(2)
    with status_col:
        st.markdown("#### Status Hardware")
        if status_rows:
            st.dataframe(pd.DataFrame(status_rows), width="stretch", hide_index=True)
        else:
            st.info("Belum ada status hardware NAS.")
    with temp_col:
        st.markdown("#### Temperatur Disk")
        if temperature_rows:
            st.dataframe(pd.DataFrame(temperature_rows), width="stretch", hide_index=True)
        else:
            st.info("Belum ada temperatur disk NAS.")


__all__ = ["_render_nas_history_section"]
