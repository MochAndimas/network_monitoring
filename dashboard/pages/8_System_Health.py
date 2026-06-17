"""Streamlit dashboard page for operational health and runtime diagnostics."""

import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp
from components.ui import (
    freshness_label,
    normalize_status_label,
    render_kpi_cards,
    render_meta_row,
    render_page_header,
    render_section_header_with_download,
)


st.set_page_config(page_title="System Health", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "System Health",
    "Status runtime backend, database, scheduler, dan observability pipeline.",
)

auto_refresh, interval_seconds = refresh_controls("system_health", default_enabled=True, default_interval=30)


def _prepare_scheduler_frame(rows: list[dict]) -> pd.DataFrame:
    """Prepare scheduler job rows for display and export."""
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        return dataframe
    for column_name in ("last_started_at", "last_succeeded_at", "last_failed_at"):
        if column_name in dataframe.columns:
            dataframe[column_name] = to_wib_timestamp(dataframe[column_name])
            dataframe[f"{column_name}_wib"] = dataframe[column_name].apply(format_wib_timestamp)
    dataframe["last_success_freshness"] = dataframe.get("last_succeeded_at", pd.Series(dtype=object)).map(
        lambda value: freshness_label(value, fresh_minutes=5, stale_minutes=15)
    )
    dataframe["state"] = dataframe.apply(_scheduler_state, axis=1)
    dataframe["last_duration_ms"] = pd.to_numeric(dataframe.get("last_duration_ms"), errors="coerce")
    return dataframe


def _scheduler_state(row: pd.Series) -> str:
    """Return a human-readable scheduler state."""
    if bool(row.get("is_running")):
        return "Running"
    if int(row.get("consecutive_failures") or 0) > 0:
        return "Failing"
    if row.get("last_succeeded_at") is not None and not pd.isna(row.get("last_succeeded_at")):
        return "OK"
    return "No data"


def _prepare_alert_frame(rows: list[dict]) -> pd.DataFrame:
    """Prepare operational alert rows for display and export."""
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        return dataframe
    dataframe["severity"] = dataframe["severity"].map(normalize_status_label)
    dataframe["last_error"] = dataframe["last_error"].fillna("-")
    return dataframe


def _prepare_freshness_frame(payload: dict) -> pd.DataFrame:
    """Prepare collector/site freshness rows for display and export."""
    dataframe = pd.DataFrame(payload.get("items", []))
    if dataframe.empty:
        return dataframe
    for column_name in ("latest_checked_at", "oldest_checked_at"):
        dataframe[column_name] = to_wib_timestamp(dataframe[column_name])
        dataframe[f"{column_name}_wib"] = dataframe[column_name].apply(format_wib_timestamp)
    dataframe["freshness_status"] = dataframe["freshness_status"].map(normalize_status_label)
    return dataframe


def _render_system_health_body() -> None:
    """Render the System Health dashboard body."""
    summary = get_json(
        "/observability/summary",
        {
            "database": "unknown",
            "devices_total": 0,
            "metrics_latest_snapshot": 0,
            "alerts_active": 0,
            "incidents_active": 0,
            "thresholds_total": 0,
            "auth": {},
            "runtime": {},
            "scheduler_jobs": [],
            "operational_alerts": [],
        },
    )
    dependencies = get_json(
        "/health/dependencies",
        {
            "database": "unknown",
            "scheduler_jobs": [],
            "scheduler_alerts": [],
        },
    )
    freshness_payload = get_json(
        "/metrics/freshness/summary?stale_after_minutes=5&active_only=true",
        {
            "generated_at": None,
            "stale_after_minutes": 5,
            "active_only": True,
            "items": [],
        },
    )

    scheduler_frame = _prepare_scheduler_frame(list(summary.get("scheduler_jobs", [])))
    operational_alerts = list(summary.get("operational_alerts", [])) or list(dependencies.get("scheduler_alerts", []))
    alert_frame = _prepare_alert_frame(operational_alerts)
    freshness_frame = _prepare_freshness_frame(freshness_payload)
    auth = summary.get("auth", {}) if isinstance(summary.get("auth"), dict) else {}
    runtime = summary.get("runtime", {}) if isinstance(summary.get("runtime"), dict) else {}

    database_status = normalize_status_label(summary.get("database"))
    scheduler_status = "Degraded" if operational_alerts else "Up"
    running_jobs = int(scheduler_frame["is_running"].sum()) if not scheduler_frame.empty and "is_running" in scheduler_frame else 0
    failing_jobs = (
        int((pd.to_numeric(scheduler_frame["consecutive_failures"], errors="coerce").fillna(0) > 0).sum())
        if not scheduler_frame.empty and "consecutive_failures" in scheduler_frame
        else 0
    )

    render_meta_row(
        [
            ("Refresh Otomatis", live_status_text(auto_refresh, interval_seconds)),
            ("Terakhir Diperbarui", rendered_at_label()),
            ("Database", database_status),
            ("Scheduler", scheduler_status),
            ("Operational Alerts", len(operational_alerts)),
        ]
    )

    render_kpi_cards(
        [
            ("Device Terdaftar", int(summary.get("devices_total", 0) or 0), None),
            ("Latest Metric", int(summary.get("metrics_latest_snapshot", 0) or 0), None),
            ("Alert Aktif", int(summary.get("alerts_active", 0) or 0), None),
            ("Incident Aktif", int(summary.get("incidents_active", 0) or 0), None),
            ("Job Running", running_jobs, None),
            ("Job Failing", failing_jobs, None),
        ],
        columns_per_row=6,
    )

    if alert_frame.empty:
        st.success("Tidak ada operational alert scheduler. Cek job status untuk freshness tiap collector.")
    else:
        st.warning("Ada operational alert scheduler yang perlu ditinjau.")
        alert_view = alert_frame[["job_name", "severity", "reason", "message", "last_error"]].rename(
            columns={
                "job_name": "Job",
                "severity": "Severity",
                "reason": "Reason",
                "message": "Message",
                "last_error": "Last Error",
            }
        )
        render_section_header_with_download(
            "Operational Alerts",
            alert_view,
            file_name="system_health_operational_alerts.csv",
            key="download_system_health_operational_alerts",
        )
        st.dataframe(alert_view, width="stretch", hide_index=True)

    if scheduler_frame.empty:
        st.markdown("### Scheduler Jobs")
        st.info("Belum ada status scheduler. Pastikan service scheduler sudah berjalan minimal satu kali.")
    else:
        scheduler_view = scheduler_frame[
            [
                "job_name",
                "state",
                "consecutive_failures",
                "last_started_at_wib",
                "last_succeeded_at_wib",
                "last_failed_at_wib",
                "last_duration_ms",
                "last_success_freshness",
            ]
        ].rename(
            columns={
                "job_name": "Job",
                "state": "State",
                "consecutive_failures": "Failures",
                "last_started_at_wib": "Last Started (WIB)",
                "last_succeeded_at_wib": "Last Succeeded (WIB)",
                "last_failed_at_wib": "Last Failed (WIB)",
                "last_duration_ms": "Duration (ms)",
                "last_success_freshness": "Freshness",
            }
        )
        render_section_header_with_download(
            "Scheduler Jobs",
            scheduler_view,
            file_name="system_health_scheduler_jobs.csv",
            key="download_system_health_scheduler_jobs",
        )
        st.dataframe(
            scheduler_view,
            width="stretch",
            hide_index=True,
            column_config={
                "Job": st.column_config.TextColumn("Job", width="medium"),
                "State": st.column_config.TextColumn("State", width="small"),
                "Failures": st.column_config.NumberColumn("Failures", width="small", format="%d"),
                "Duration (ms)": st.column_config.NumberColumn("Duration (ms)", width="small", format="%.2f"),
                "Freshness": st.column_config.TextColumn("Freshness", width="medium"),
            },
        )

    if freshness_frame.empty:
        st.markdown("### Freshness per Collector/Site")
        st.info("Belum ada data freshness. Pastikan scheduler sudah menghasilkan latest metric snapshot.")
    else:
        freshness_view = freshness_frame[
            [
                "collector",
                "site",
                "freshness_status",
                "total_devices",
                "devices_with_data",
                "fresh_devices",
                "stale_devices",
                "no_data_devices",
                "latest_checked_at_wib",
                "oldest_checked_at_wib",
            ]
        ].rename(
            columns={
                "collector": "Collector",
                "site": "Site",
                "freshness_status": "Freshness",
                "total_devices": "Total Device",
                "devices_with_data": "With Data",
                "fresh_devices": "Fresh",
                "stale_devices": "Stale",
                "no_data_devices": "No Data",
                "latest_checked_at_wib": "Latest Check (WIB)",
                "oldest_checked_at_wib": "Oldest Check (WIB)",
            }
        )
        render_section_header_with_download(
            "Freshness per Collector/Site",
            freshness_view,
            file_name="system_health_freshness.csv",
            key="download_system_health_freshness",
        )
        st.caption(
            "Freshness dihitung dari latest metric snapshot device aktif. "
            f"Bucket dianggap stale jika tidak ada data baru dalam {freshness_payload.get('stale_after_minutes', 5)} menit."
        )
        st.dataframe(
            freshness_view,
            width="stretch",
            hide_index=True,
            column_config={
                "Collector": st.column_config.TextColumn("Collector", width="medium"),
                "Site": st.column_config.TextColumn("Site", width="medium"),
                "Freshness": st.column_config.TextColumn("Freshness", width="small"),
                "Total Device": st.column_config.NumberColumn("Total Device", width="small", format="%d"),
                "With Data": st.column_config.NumberColumn("With Data", width="small", format="%d"),
                "Fresh": st.column_config.NumberColumn("Fresh", width="small", format="%d"),
                "Stale": st.column_config.NumberColumn("Stale", width="small", format="%d"),
                "No Data": st.column_config.NumberColumn("No Data", width="small", format="%d"),
            },
        )

    auth_col, runtime_col = st.columns(2)
    with auth_col:
        st.markdown("### Auth Observability")
        auth_frame = pd.DataFrame(
            [
                ("Active Sessions", int(auth.get("active_sessions", 0) or 0)),
                ("Login Failures Window", int(auth.get("login_failures_window", 0) or 0)),
                ("Rate Limited Window", int(auth.get("login_rate_limited_window", 0) or 0)),
                ("Revoked Sessions Window", int(auth.get("revoked_sessions_window", 0) or 0)),
            ],
            columns=["Metric", "Value"],
        )
        st.dataframe(auth_frame, width="stretch", hide_index=True)

    with runtime_col:
        st.markdown("### Runtime")
        runtime_frame = pd.DataFrame(
            [(str(key), str(value)) for key, value in sorted(runtime.items())],
            columns=["Key", "Value"],
        )
        if runtime_frame.empty:
            st.info("Runtime info belum tersedia dari backend.")
        else:
            st.dataframe(runtime_frame, width="stretch", hide_index=True)


render_live_section(auto_refresh, interval_seconds, _render_system_health_body)
