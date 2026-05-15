"""Live monitoring device-specific rendering helpers."""


import altair as alt
import pandas as pd
import streamlit as st
from typing import Any

from .constants import (
    NAS_CARD_ONLY_METRIC_NAMES,
    PRINTER_METRIC_NAMES as PRINTER_METRIC_NAMES,
    STATUS_OPTIONS as STATUS_OPTIONS,
)
from .formatting import (
    _dynamic_mikrotik_metric_label as _dynamic_mikrotik_metric_label,
    _dynamic_nas_metric_label as _dynamic_nas_metric_label,
    _format_duration as _format_duration,
    _format_metric_value as _format_metric_value,
    _format_metric_value_components as _format_metric_value_components,
    _format_metric_values as _format_metric_values,
    _friendly_metric_name as _friendly_metric_name,
    _has_unit as _has_unit,
    _humanize_printer_text as _humanize_printer_text,
    _metric_filter_label as _metric_filter_label,
    _y_axis_label as _y_axis_label,
)

from .data import _is_nas_card_only_metric
from .rendering import _format_celsius, _render_stat_card, _status_label_for_display

def _latest_metric_snapshot_map(dataframe: pd.DataFrame) -> dict[str, pd.Series]:
    """Return latest latest metric snapshot map used by dashboard payloads."""
    if dataframe.empty:
        return {}
    latest_rows = dataframe.sort_values("checked_at").drop_duplicates(subset=["metric_name"], keep="last")
    return {str(row["metric_name"]): row for _, row in latest_rows.iterrows()}


def _latest_metric_value_from_map(
    latest_map: dict[str, pd.Series],
    metric_name: str,
    default: str = "-",
) -> str:
    """Return latest latest metric value from map used by dashboard payloads."""
    row = latest_map.get(metric_name)
    if row is None:
        return default
    return str(row.get("metric_value") or default)


def _latest_metric_display_from_map(
    latest_map: dict[str, pd.Series],
    metric_name: str,
    default: str = "-",
) -> str:
    """Return latest formatted metric display value from map."""
    row = latest_map.get(metric_name)
    if row is None:
        return default
    return str(row.get("display_value") or row.get("metric_value") or default)


def _nas_volume_capacity_view(latest_map: dict[str, pd.Series]) -> pd.DataFrame:
    """Return latest NAS volume capacity rows grouped by volume."""
    volumes: dict[str, dict[str, object]] = {}
    for metric_name, row in latest_map.items():
        parts = str(metric_name or "").split(":")
        if len(parts) != 3 or parts[0] != "nas_volume":
            continue
        volume_key = parts[1]
        metric_key = parts[2]
        volume = volumes.setdefault(
            volume_key,
            {
                "Volume": volume_key.replace("_", " ").title(),
                "Status": "-",
                "Total": "-",
                "Terpakai": "-",
                "Sisa": "-",
                "Used": "-",
                "Dicek (WIB)": row.get("checked_at_wib"),
            },
        )
        if metric_key == "status":
            volume["Status"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "total_bytes":
            volume["Total"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "used_bytes":
            volume["Terpakai"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "free_bytes":
            volume["Sisa"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "used_percent":
            volume["Used"] = _format_percent(str(row.get("metric_value") or row.get("metric_value_numeric") or ""))
        checked_at = row.get("checked_at_wib")
        if checked_at:
            volume["Dicek (WIB)"] = checked_at
    if not volumes:
        return pd.DataFrame()
    return pd.DataFrame(volumes.values()).sort_values("Volume")


def _format_percent(value: str) -> str:
    """Format percent for the live monitoring dashboard."""
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _format_bytes(value: float | int | None) -> str:
    """Format bytes for the live monitoring dashboard."""
    if value is None or pd.isna(value):
        return "-"
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "-"


def _format_mbps(value: float | int | None) -> str:
    """Format mbps for the live monitoring dashboard."""
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def _dynamic_mikrotik_metric_table(dataframe: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Return dynamic mikrotik metric table for the live monitoring dashboard."""
    if dataframe.empty:
        return pd.DataFrame()

    latest_rows = dataframe.sort_values("checked_at").drop_duplicates(subset=["metric_name"], keep="last")
    rows = latest_rows[latest_rows["metric_name"].astype(str).str.startswith(f"{prefix}:")].copy()
    if rows.empty:
        return pd.DataFrame()

    parsed_rows: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        parts = str(row["metric_name"]).split(":")
        group_key: str | tuple[str, str]
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
    """Return interface view for the live monitoring dashboard."""
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
    """Return firewall view for the live monitoring dashboard."""
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
    """Render Mikrotik-specific interface and firewall history views."""
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


def _is_dynamic_mikrotik_metric(metric_name: str) -> bool:
    """Return whether is dynamic mikrotik metric applies in the live monitoring dashboard."""
    return str(metric_name or "").startswith(("interface:", "queue:", "firewall:"))


def _default_mikrotik_trend_metrics(metric_names: list[str]) -> list[str]:
    """Return default mikrotik trend metrics for the live monitoring dashboard."""
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
    """Render printer-specific status and consumable history views."""
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


__all__ = ['_latest_metric_snapshot_map', '_latest_metric_value_from_map', '_latest_metric_display_from_map', '_nas_volume_capacity_view', '_format_percent', '_format_bytes', '_format_mbps', '_dynamic_mikrotik_metric_table', '_interface_view', '_firewall_view', '_render_mikrotik_history_section', '_render_nas_history_section', '_is_dynamic_mikrotik_metric', '_default_mikrotik_trend_metrics', '_render_printer_history_section']
