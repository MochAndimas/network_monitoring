"""NAS-specific live monitoring helpers."""

import pandas as pd
import streamlit as st

try:
    from components.ui import render_paginated_dataframe
except ModuleNotFoundError:  # pragma: no cover - supports imports outside Streamlit's app root
    from dashboard.components.ui import render_paginated_dataframe

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
        st.info(
            "Belum ada metrik NAS SNMP. Pastikan device bertipe `nas`, NAS target adalah Synology, "
            "`NAS_SNMP_COMMUNITIES` berisi IP NAS, SNMP v2c aktif, UDP 161 terbuka, "
            "lalu jalankan monitoring cycle."
        )
        return

    latest_map = _latest_metric_snapshot_map(nas_history_frame)
    collection_row = latest_map.get("nas_snmp_collection_status")
    volume_capacity_frame = _nas_volume_capacity_view(latest_map)
    st.markdown("### Kesehatan NAS")
    if collection_row is not None and str(collection_row["display_value"]).lower() != "ok":
        st.warning(
            f"Data NAS SNMP belum dapat dikumpulkan ({collection_row['display_value']}). "
            "Status volume, RAID, disk, dan temperatur mungkin bukan kondisi terbaru. "
            "Cek VPN/ACL UDP 161, community read-only, dan SNMP v2c Synology."
        )
    health_cards = [
        ("Kolektor SNMP", _latest_metric_value_from_map(latest_map, "nas_snmp_collection_status")),
        ("CPU", _format_percent(_latest_metric_value_from_map(latest_map, "cpu_percent"))),
        ("Memory", _format_percent(_latest_metric_value_from_map(latest_map, "memory_percent"))),
        ("Volume Used", _format_percent(_latest_metric_value_from_map(latest_map, "disk_percent"))),
        ("System Temp", _format_celsius(_latest_metric_value_from_map(latest_map, "nas_system_temperature_c"))),
        ("System", _latest_metric_value_from_map(latest_map, "nas_system_status")),
        ("Uptime", _latest_metric_display_from_map(latest_map, "nas_uptime_seconds")),
    ]
    for cards_in_row in (health_cards[:4], health_cards[4:]):
        for column, (label, value) in zip(st.columns(len(cards_in_row)), cards_in_row, strict=False):
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
        st.info("Belum ada detail kapasitas volume NAS. Cek permission SNMP Synology dan OID storage/RAID.")
    else:
        render_paginated_dataframe(
            volume_capacity_frame,
            key="nas_volume_capacity_table",
            label="Volume NAS",
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
            render_paginated_dataframe(
                pd.DataFrame(status_rows),
                key="nas_hardware_status_table",
                label="Status Hardware",
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Belum ada status hardware NAS. Cek SNMP Synology MIB untuk system, power, fan, RAID, dan disk.")
    with temp_col:
        st.markdown("#### Temperatur Disk")
        if temperature_rows:
            render_paginated_dataframe(
                pd.DataFrame(temperature_rows),
                key="nas_disk_temperature_table",
                label="Temperatur Disk",
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Belum ada temperatur disk NAS. Pastikan disk temperature tersedia lewat SNMP Synology.")


__all__ = ["_render_nas_history_section"]
