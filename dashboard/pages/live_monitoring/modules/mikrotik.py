"""Mikrotik-specific live monitoring helpers."""

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from .device_common import _format_bytes, _format_mbps, _format_percent, _latest_metric_snapshot_map, _latest_metric_value_from_map
from .rendering import _render_stat_card

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

__all__ = [
    "_default_mikrotik_trend_metrics",
    "_dynamic_mikrotik_metric_table",
    "_firewall_view",
    "_interface_view",
    "_is_dynamic_mikrotik_metric",
    "_render_mikrotik_history_section",
]
