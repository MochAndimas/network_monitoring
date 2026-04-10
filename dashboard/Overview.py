import pandas as pd
import streamlit as st

from components.api import get_json, post_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp


STATUS_EMOJI = {
    "up": "UP",
    "ok": "OK",
    "warning": "WARNING",
    "down": "DOWN",
    "error": "ERROR",
    "unknown": "UNKNOWN",
}


OVERVIEW_CSS = """
<style>
.stMainBlockContainer,
[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 100%;
    padding-left: 2rem;
    padding-right: 2rem;
}
.overview-meta {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin: 0.25rem 0 1.25rem 0;
}
.overview-pill {
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.03);
    border-radius: 999px;
    padding: 0.45rem 0.8rem;
    font-size: 0.9rem;
    color: rgba(250,250,250,0.8);
}
.stat-card {
    border: 1px solid rgba(255,255,255,0.08);
    background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02));
    border-radius: 18px;
    padding: 1rem 1rem 0.95rem 1rem;
    min-height: 126px;
    margin-bottom: 0.4rem;
}
.stat-card-label {
    font-size: 0.92rem;
    line-height: 1.35;
    color: rgba(250,250,250,0.72);
    margin-bottom: 0.65rem;
}
.stat-card-value {
    font-size: clamp(1.6rem, 2.2vw, 2.8rem);
    line-height: 1.08;
    font-weight: 700;
    color: #f8fafc;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.stat-card-value.compact {
    font-size: clamp(1.05rem, 1.5vw, 1.55rem);
    line-height: 1.25;
}
</style>
"""


def _status_label(value: str | None) -> str:
    if not value:
        return STATUS_EMOJI["unknown"]
    return STATUS_EMOJI.get(str(value).lower(), str(value).upper())


def _render_stat_card(column, label: str, value: str | int, *, compact: bool = False) -> None:
    value_class = "stat-card-value compact" if compact else "stat-card-value"
    column.markdown(
        f"""
        <div class="stat-card">
            <div class="stat-card-label">{label}</div>
            <div class="{value_class}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _prepare_devices_frame(devices: list[dict]) -> pd.DataFrame:
    dataframe = pd.DataFrame(devices)
    if dataframe.empty:
        return dataframe
    if "latest_checked_at" in dataframe.columns:
        dataframe["latest_checked_at"] = to_wib_timestamp(dataframe["latest_checked_at"])
        dataframe["latest_checked_at_wib"] = dataframe["latest_checked_at"].apply(format_wib_timestamp)
    else:
        dataframe["latest_checked_at_wib"] = "-"
    dataframe["site"] = dataframe["site"].fillna("-")
    dataframe["latest_status"] = dataframe["latest_status"].fillna("unknown")
    return dataframe


def _prepare_alerts_frame(alerts: list[dict]) -> pd.DataFrame:
    dataframe = pd.DataFrame(alerts)
    if dataframe.empty:
        return dataframe
    dataframe["created_at"] = to_wib_timestamp(dataframe["created_at"])
    dataframe["created_at_wib"] = dataframe["created_at"].apply(format_wib_timestamp)
    return dataframe


def _prepare_incidents_frame(incidents: list[dict]) -> pd.DataFrame:
    dataframe = pd.DataFrame(incidents)
    if dataframe.empty:
        return dataframe
    dataframe["started_at"] = to_wib_timestamp(dataframe["started_at"])
    dataframe["started_at_wib"] = dataframe["started_at"].apply(format_wib_timestamp)
    return dataframe


def _render_overview_body() -> None:
    summary = get_json(
        "/dashboard/summary",
        {
            "internet_status": "unknown",
            "mikrotik_status": "unknown",
            "server_status": "unknown",
            "active_alerts": 0,
        },
    )
    devices = get_json("/devices", [])
    alerts = get_json("/alerts/active", [])
    incidents = get_json("/incidents?status=active", [])
    recent_history = get_json("/metrics/history?limit=100", [])

    devices_frame = _prepare_devices_frame(devices)
    alerts_frame = _prepare_alerts_frame(alerts)
    incidents_frame = _prepare_incidents_frame(incidents)
    history_frame = pd.DataFrame(recent_history)
    if not history_frame.empty and "checked_at" in history_frame.columns:
        history_frame["checked_at"] = to_wib_timestamp(history_frame["checked_at"])
        history_frame["checked_at_wib"] = history_frame["checked_at"].apply(format_wib_timestamp)

    total_devices = int(len(devices_frame)) if not devices_frame.empty else 0
    active_devices = int(devices_frame["is_active"].sum()) if not devices_frame.empty else 0
    devices_down = int((devices_frame["latest_status"] == "down").sum()) if not devices_frame.empty else 0
    devices_warning = int((devices_frame["latest_status"] == "warning").sum()) if not devices_frame.empty else 0
    active_incidents = int(len(incidents_frame)) if not incidents_frame.empty else 0
    latest_check = (
        format_wib_timestamp(devices_frame["latest_checked_at"].max())
        if not devices_frame.empty and devices_frame["latest_checked_at"].notna().any()
        else "-"
    )

    st.markdown(
        f"""
        <div class="overview-meta">
            <div class="overview-pill">{live_status_text(auto_refresh, interval_seconds)}</div>
            <div class="overview-pill">Render terakhir: {rendered_at_label()}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Global Status")
    status_col1, status_col2, status_col3, status_col4 = st.columns(4)
    _render_stat_card(status_col1, "Internet", _status_label(summary["internet_status"]))
    _render_stat_card(status_col2, "Mikrotik", _status_label(summary["mikrotik_status"]))
    _render_stat_card(status_col3, "Server", _status_label(summary["server_status"]))
    _render_stat_card(status_col4, "Active Alerts", int(summary["active_alerts"]))

    st.markdown("### Operational Snapshot")
    ops_col1, ops_col2, ops_col3, ops_col4, ops_col5 = st.columns(5)
    _render_stat_card(ops_col1, "Total Devices", total_devices)
    _render_stat_card(ops_col2, "Active Devices", active_devices)
    _render_stat_card(ops_col3, "Devices Down", devices_down)
    _render_stat_card(ops_col4, "Devices Warning", devices_warning)
    _render_stat_card(ops_col5, "Last Check (WIB)", latest_check, compact=True)

    ops_left, ops_right = st.columns([2, 1])

    with ops_left:
        st.markdown("### Devices Needing Attention")
        if devices_frame.empty:
            st.info("Belum ada device yang tersedia.")
        else:
            problem_devices = devices_frame[devices_frame["latest_status"].isin(["down", "warning", "error"])].copy()
            if problem_devices.empty:
                st.success("Semua device aktif saat ini terlihat sehat dari snapshot terbaru.")
            else:
                problem_view = problem_devices[
                    ["name", "ip_address", "device_type", "site", "latest_status", "latest_checked_at_wib"]
                ].rename(
                    columns={
                        "name": "Device",
                        "ip_address": "IP Address",
                        "device_type": "Type",
                        "site": "Site",
                        "latest_status": "Status",
                        "latest_checked_at_wib": "Last Check (WIB)",
                    }
                )
                st.dataframe(problem_view, width="stretch", hide_index=True)

    with ops_right:
        st.markdown("### Alert Severity")
        if alerts_frame.empty:
            st.success("Tidak ada alert aktif.")
        else:
            severity_counts = alerts_frame["severity"].fillna("unknown").value_counts().rename_axis("severity").reset_index(name="count")
            st.bar_chart(severity_counts.set_index("severity"))
            st.metric("Active Incidents", active_incidents)

    insight_left, insight_right = st.columns(2)

    with insight_left:
        st.markdown("### Latest Active Alerts")
        if alerts_frame.empty:
            st.info("Belum ada alert aktif.")
        else:
            latest_alerts_view = alerts_frame.sort_values("created_at", ascending=False)[
                ["created_at_wib", "device_name", "severity", "message"]
            ].rename(
                columns={
                    "created_at_wib": "Created At (WIB)",
                    "device_name": "Device",
                    "severity": "Severity",
                    "message": "Message",
                }
            )
            st.dataframe(latest_alerts_view.head(5), width="stretch", hide_index=True)

    with insight_right:
        st.markdown("### Active Incidents")
        if incidents_frame.empty:
            st.info("Belum ada incident aktif.")
        else:
            incident_view = incidents_frame.sort_values("started_at", ascending=False)[
                ["started_at_wib", "device_name", "summary", "status"]
            ].rename(
                columns={
                    "started_at_wib": "Started At (WIB)",
                    "device_name": "Device",
                    "summary": "Summary",
                    "status": "Status",
                }
            )
            st.dataframe(incident_view.head(5), width="stretch", hide_index=True)

    st.markdown("### Recent Metric Snapshot")
    if history_frame.empty:
        st.info("Belum ada metric history yang bisa ditampilkan.")
    else:
        metric_snapshot = (
            history_frame.sort_values("checked_at", ascending=False)
            .drop_duplicates(subset=["device_name", "metric_name"])
            .copy()
        )
        metric_snapshot["value"] = metric_snapshot.apply(
            lambda row: f'{row["metric_value"]}{f" {row["unit"]}" if row.get("unit") else ""}',
            axis=1,
        )
        metric_view = metric_snapshot[
            ["checked_at_wib", "device_name", "metric_name", "value", "status"]
        ].rename(
            columns={
                "checked_at_wib": "Checked At (WIB)",
                "device_name": "Device",
                "metric_name": "Metric",
                "value": "Value",
                "status": "Status",
            }
        )
        st.dataframe(metric_view.head(12), width="stretch", hide_index=True)


st.set_page_config(page_title="Overview", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
st.markdown(OVERVIEW_CSS, unsafe_allow_html=True)
st.title("Overview")
st.caption("Overview ini dipakai buat lihat kondisi umum sistem, gangguan aktif, dan snapshot device terbaru tanpa pindah-pindah halaman.")

action_col, info_col = st.columns([1, 3])
with action_col:
    if st.button("Run Monitoring Cycle Now", type="primary", width="stretch"):
        cycle_result = post_json(
            "/system/run-cycle",
            None,
            {
                "metrics_collected": 0,
                "alerts_created": 0,
                "alerts_resolved": 0,
                "incidents_created": 0,
                "incidents_resolved": 0,
            },
        )
        st.success(
            "Cycle selesai: "
            f"metrics={cycle_result['metrics_collected']}, "
            f"alerts baru={cycle_result['alerts_created']}, "
            f"alerts resolved={cycle_result['alerts_resolved']}, "
            f"incidents baru={cycle_result['incidents_created']}"
        )
with info_col:
    st.info(
        "Gunakan halaman ini untuk quick check. "
        "Kalau butuh detail histori, inventory, atau threshold, lanjut lewat menu sidebar."
    )

auto_refresh, interval_seconds = refresh_controls("overview", default_enabled=True, default_interval=15)
render_live_section(auto_refresh, interval_seconds, _render_overview_body)
