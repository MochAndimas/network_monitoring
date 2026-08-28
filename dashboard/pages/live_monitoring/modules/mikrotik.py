"""Mikrotik-specific live monitoring helpers."""

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    from components.ui import render_paginated_dataframe
except ModuleNotFoundError:  # pragma: no cover - supports imports outside Streamlit's app root
    from dashboard.components.ui import render_paginated_dataframe

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
        st.info(
            "Belum ada metrik Mikrotik API. Pastikan device bertipe `mikrotik`, "
            "`MIKROTIK_HOST`, `MIKROTIK_USERNAME`, dan `MIKROTIK_PASSWORD` benar, "
            "service RouterOS API aktif, firewall mengizinkan scheduler, lalu jalankan monitoring cycle."
        )
        return

    latest_map = _latest_metric_snapshot_map(mikrotik_history_frame)
    api_status = _latest_metric_value_from_map(latest_map, "mikrotik_api")
    interface_frame = _interface_view(mikrotik_history_frame)
    firewall_frame = _firewall_view(mikrotik_history_frame)

    st.markdown("### Metrik Mikrotik")
    if str(api_status or "").lower() not in {"", "ok"}:
        st.warning(
            f"Collector RouterOS API bermasalah ({api_status}). Data CPU, client, interface, queue, dan firewall mungkin stale. "
            "Cek VPN/routing, service API dan port RouterOS, serta username/password read-only."
        )
    health_col1, health_col2, health_col3, health_col4, health_col5, health_col6 = st.columns(6)
    _render_stat_card(health_col1, "RouterOS API", str(api_status or "-"))
    _render_stat_card(health_col2, "CPU Load", _format_percent(_latest_metric_value_from_map(latest_map, "cpu_percent")))
    _render_stat_card(
        health_col3,
        "Memory Used",
        _format_percent(_latest_metric_value_from_map(latest_map, "memory_percent")),
    )
    _render_stat_card(
        health_col4,
        "Storage Used",
        _format_percent(_latest_metric_value_from_map(latest_map, "disk_percent")),
    )
    _render_stat_card(health_col5, "DHCP Leases", _latest_metric_value_from_map(latest_map, "dhcp_active_leases"))
    _render_stat_card(health_col6, "Connected Clients", _latest_metric_value_from_map(latest_map, "connected_clients"))

    st.markdown("### Interface Traffic")
    if interface_frame.empty:
        st.info(
            "Belum ada data interface traffic. Coba perluas rentang waktu, cek `MIKROTIK_DYNAMIC_SECTIONS`, "
            "dan pastikan interface tidak tersaring oleh allowlist."
        )
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
            traffic_chart = px.bar(melted, x="Mbps", y="Interface", color="Direction", orientation="h", barmode="group")
            traffic_chart.update_layout(height=260, xaxis_title="Mbps", yaxis_title="Interface", yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(traffic_chart, width="stretch")
        with traffic_table_col:
            render_paginated_dataframe(
                interface_frame,
                key="mikrotik_interface_table",
                label="Interface",
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
        st.info(
            "Belum ada counter firewall/NAT. Pastikan `MIKROTIK_DYNAMIC_SECTIONS` memuat `firewall` "
            "dan firewall section ada di allowlist."
        )
    else:
        render_paginated_dataframe(
            firewall_frame,
            key="mikrotik_firewall_table",
            label="Firewall",
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
