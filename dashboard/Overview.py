import altair as alt
import pandas as pd
import streamlit as st

from components.auth import is_admin, require_dashboard_login, session_expiry_label
from components.api import get_json, has_pending_action, post_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp
from components.ui import normalize_status_label, render_kpi_cards, render_meta_row, render_page_header, status_priority


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
    dataframe["latest_status_label"] = dataframe["latest_status"].map(normalize_status_label)
    return dataframe


def _prepare_alerts_frame(alerts: list[dict]) -> pd.DataFrame:
    dataframe = pd.DataFrame(alerts)
    if dataframe.empty:
        return dataframe
    dataframe["created_at"] = to_wib_timestamp(dataframe["created_at"])
    dataframe["created_at_wib"] = dataframe["created_at"].apply(format_wib_timestamp)
    dataframe["severity"] = dataframe["severity"].map(normalize_status_label)
    return dataframe


def _prepare_incidents_frame(incidents: list[dict]) -> pd.DataFrame:
    dataframe = pd.DataFrame(incidents)
    if dataframe.empty:
        return dataframe
    dataframe["started_at"] = to_wib_timestamp(dataframe["started_at"])
    dataframe["started_at_wib"] = dataframe["started_at"].apply(format_wib_timestamp)
    dataframe["status"] = dataframe["status"].map(normalize_status_label)
    return dataframe


def _prepare_snapshot_frame(snapshot_payload: dict) -> pd.DataFrame:
    dataframe = pd.DataFrame(snapshot_payload.get("items", []))
    if dataframe.empty:
        return dataframe
    dataframe["checked_at"] = to_wib_timestamp(dataframe["checked_at"])
    dataframe["checked_at_wib"] = dataframe["checked_at"].apply(format_wib_timestamp)
    unit_series = dataframe["unit"].fillna("").astype(str)
    dataframe["value"] = dataframe["metric_value"].astype(str) + unit_series.map(lambda unit: f" {unit}" if unit else "")
    dataframe["status"] = dataframe["status"].map(normalize_status_label)
    return dataframe


def _render_overview_body() -> None:
    payload = get_json(
        "/dashboard/overview-data",
        {
            "summary": {
                "internet_status": "unknown",
                "mikrotik_status": "unknown",
                "server_status": "unknown",
                "active_alerts": 0,
            },
            "device_counts": {
                "total": 0,
                "active": 0,
                "inactive": 0,
                "statuses": {},
                "latest_check_at": None,
            },
            "alert_severity_summary": {},
            "alerts": [],
            "incidents": [],
            "latest_snapshot": {"items": [], "meta": {}},
            "problem_devices": [],
        },
    )
    summary = payload["summary"]
    device_counts = payload["device_counts"]
    problem_devices = payload["problem_devices"]
    alerts = payload["alerts"]
    incidents = payload["incidents"]
    latest_snapshot = payload["latest_snapshot"]

    devices_frame = _prepare_devices_frame(problem_devices)
    alerts_frame = _prepare_alerts_frame(alerts)
    incidents_frame = _prepare_incidents_frame(incidents)
    history_frame = _prepare_snapshot_frame(latest_snapshot)

    total_devices = int(device_counts.get("total", 0) or 0)
    active_devices = int(device_counts.get("active", 0) or 0)
    status_counts = device_counts.get("statuses", {}) if isinstance(device_counts.get("statuses"), dict) else {}
    devices_down = int(status_counts.get("down", 0) or 0)
    devices_warning = int(status_counts.get("warning", 0) or 0)
    active_incidents = int(len(incidents_frame)) if not incidents_frame.empty else 0
    latest_check = (
        format_wib_timestamp(to_wib_timestamp(device_counts.get("latest_check_at")))
        if device_counts.get("latest_check_at")
        else "-"
    )
    severity_counts = pd.DataFrame(
        [{"severity": normalize_status_label(severity), "count": count} for severity, count in payload.get("alert_severity_summary", {}).items()]
    )
    if not severity_counts.empty:
        severity_counts["priority"] = severity_counts["severity"].map(status_priority)
        severity_counts = severity_counts.sort_values(["priority", "count", "severity"], ascending=[True, False, True])

    render_meta_row(
        [
            ("Refresh Otomatis", live_status_text(auto_refresh, interval_seconds)),
            ("Terakhir Diperbarui", rendered_at_label()),
            ("Pemeriksaan Terakhir (WIB)", latest_check),
        ]
    )

    st.subheader("Status Global")
    render_kpi_cards(
        [
            ("Internet", normalize_status_label(summary["internet_status"]), None),
            ("Mikrotik", normalize_status_label(summary["mikrotik_status"]), None),
            ("Server", normalize_status_label(summary["server_status"]), None),
            ("Alert Aktif", int(summary["active_alerts"]), None),
        ],
        columns_per_row=4,
    )

    st.subheader("Snapshot Operasional")
    render_kpi_cards(
        [
            ("Total Device", total_devices, None),
            ("Device Aktif", active_devices, None),
            ("Device Down", devices_down, None),
            ("Device Warning", devices_warning, None),
            ("Insiden Aktif", active_incidents, None),
        ],
        columns_per_row=5,
    )

    ops_left, ops_right = st.columns([2, 1])

    with ops_left:
        st.markdown("### Device Perlu Perhatian")
        if devices_frame.empty:
            st.info("Belum ada device yang tersedia.")
        else:
            filtered_devices = devices_frame[devices_frame["latest_status"].isin(["down", "warning", "error"])].copy()
            if filtered_devices.empty:
                st.success("Semua device aktif saat ini terlihat sehat dari snapshot terbaru.")
            else:
                problem_view = filtered_devices[
                    ["name", "ip_address", "device_type", "site", "latest_status_label", "latest_checked_at_wib"]
                ].rename(
                    columns={
                        "name": "Device",
                        "ip_address": "IP Address",
                        "device_type": "Type",
                        "site": "Site",
                        "latest_status_label": "Status",
                        "latest_checked_at_wib": "Pemeriksaan Terakhir (WIB)",
                    }
                )
                st.dataframe(
                    problem_view,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Device": st.column_config.TextColumn("Device", width="medium"),
                        "IP Address": st.column_config.TextColumn("IP Address", width="small"),
                        "Type": st.column_config.TextColumn("Type", width="small"),
                        "Site": st.column_config.TextColumn("Site", width="small"),
                        "Status": st.column_config.TextColumn("Status", width="small"),
                        "Pemeriksaan Terakhir (WIB)": st.column_config.TextColumn("Pemeriksaan Terakhir (WIB)", width="medium"),
                    },
                )

    with ops_right:
        st.markdown("### Distribusi Severity Alert")
        if severity_counts.empty:
            st.success("Tidak ada alert aktif.")
        else:
            severity_chart = (
                alt.Chart(severity_counts)
                .mark_bar()
                .encode(
                    x=alt.X("count:Q", title="Jumlah"),
                    y=alt.Y("severity:N", sort="-x", title="Severity"),
                    tooltip=[alt.Tooltip("severity:N", title="Severity"), alt.Tooltip("count:Q", title="Jumlah")],
                )
                .properties(height=220)
            )
            st.altair_chart(severity_chart, width="stretch")
            st.dataframe(
                severity_counts[["severity", "count"]].rename(columns={"severity": "Severity", "count": "Jumlah"}),
                width="stretch",
                hide_index=True,
                column_config={
                    "Severity": st.column_config.TextColumn("Severity", width="small"),
                    "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
                },
            )

    insight_left, insight_right = st.columns(2)

    with insight_left:
        st.markdown("### Alert Aktif Terbaru")
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
            st.dataframe(
                latest_alerts_view.head(8),
                width="stretch",
                hide_index=True,
                column_config={
                    "Created At (WIB)": st.column_config.TextColumn("Created At (WIB)", width="medium"),
                    "Device": st.column_config.TextColumn("Device", width="medium"),
                    "Severity": st.column_config.TextColumn("Severity", width="small"),
                    "Message": st.column_config.TextColumn("Message", width="large"),
                },
            )

    with insight_right:
        st.markdown("### Insiden Aktif")
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
            st.dataframe(
                incident_view.head(8),
                width="stretch",
                hide_index=True,
                column_config={
                    "Started At (WIB)": st.column_config.TextColumn("Started At (WIB)", width="medium"),
                    "Device": st.column_config.TextColumn("Device", width="medium"),
                    "Summary": st.column_config.TextColumn("Summary", width="large"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                },
            )

    st.markdown("### Snapshot Metric Terbaru")
    if history_frame.empty:
        st.info("Belum ada metric history yang bisa ditampilkan.")
    else:
        metric_view = history_frame[
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
        st.dataframe(
            metric_view.head(12),
            width="stretch",
            hide_index=True,
            column_config={
                "Checked At (WIB)": st.column_config.TextColumn("Checked At (WIB)", width="medium"),
                "Device": st.column_config.TextColumn("Device", width="medium"),
                "Metric": st.column_config.TextColumn("Metric", width="medium"),
                "Value": st.column_config.TextColumn("Value", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
            },
        )


st.set_page_config(page_title="Overview", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "Overview",
    "Ringkasan kondisi jaringan, gangguan aktif, dan snapshot telemetry terkini.",
)

action_col, info_col = st.columns([1, 3])
with action_col:
    if not is_admin():
        st.caption(f"Session expiry: {session_expiry_label()}")
        st.info("Role viewer tidak bisa menjalankan monitoring cycle manual.")
    else:
        run_cycle_clicked = st.button("Run Monitoring Cycle Now", type="primary", width="stretch")
    if is_admin() and (run_cycle_clicked or has_pending_action("run_monitoring_cycle")):
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
            action_key="run_monitoring_cycle",
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
        "Gunakan halaman ini untuk quick check operasional. "
        "Detail histori, inventory, dan threshold tetap tersedia di halaman masing-masing."
    )

auto_refresh, interval_seconds = refresh_controls("overview", default_enabled=True, default_interval=15)
render_live_section(auto_refresh, interval_seconds, _render_overview_body)
