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
    render_paginated_dataframe,
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


def _prepare_scheduler_health_frame(rows: list[dict]) -> pd.DataFrame:
    """Prepare scheduler interval and lag rows for display and export."""
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        return dataframe
    if "last_heartbeat_at" in dataframe.columns:
        dataframe["last_heartbeat_at"] = to_wib_timestamp(dataframe["last_heartbeat_at"])
        dataframe["last_heartbeat_at_wib"] = dataframe["last_heartbeat_at"].apply(format_wib_timestamp)
    for column_name in ("expected_interval_seconds", "stale_after_seconds", "heartbeat_age_seconds", "schedule_lag_seconds"):
        dataframe[column_name] = pd.to_numeric(dataframe.get(column_name), errors="coerce")
    dataframe["state"] = dataframe["state"].map(normalize_status_label)
    return dataframe


def _prepare_collector_health_frame(rows: list[dict]) -> pd.DataFrame:
    """Prepare collector success rollups for display and export."""
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        return dataframe
    dataframe["last_checked_at"] = to_wib_timestamp(dataframe["last_checked_at"])
    dataframe["last_checked_at_wib"] = dataframe["last_checked_at"].apply(format_wib_timestamp)
    dataframe["state"] = dataframe["state"].map(normalize_status_label)
    dataframe["success_rate_percent"] = pd.to_numeric(dataframe["success_rate_percent"], errors="coerce")
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
            "database_pool": {},
            "scheduler_queue": {},
            "pipeline_locks": {},
            "raw_metric_write_rate": {},
            "scheduler_jobs": [],
            "scheduler_health": [],
            "collector_health": [],
            "collector_health_window_hours": 24,
            "collector_runs": [],
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
        accepted_status_codes=(503,),
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
    scheduler_health_frame = _prepare_scheduler_health_frame(list(summary.get("scheduler_health", [])))
    collector_health_frame = _prepare_collector_health_frame(list(summary.get("collector_health", [])))
    collector_runs_frame = pd.DataFrame(list(summary.get("collector_runs", [])))
    operational_alerts = list(summary.get("operational_alerts", [])) or list(dependencies.get("scheduler_alerts", []))
    alert_frame = _prepare_alert_frame(operational_alerts)
    freshness_frame = _prepare_freshness_frame(freshness_payload)
    auth = summary.get("auth", {}) if isinstance(summary.get("auth"), dict) else {}
    runtime = summary.get("runtime", {}) if isinstance(summary.get("runtime"), dict) else {}
    database_pool = summary.get("database_pool", {}) if isinstance(summary.get("database_pool"), dict) else {}
    scheduler_queue = summary.get("scheduler_queue", {}) if isinstance(summary.get("scheduler_queue"), dict) else {}
    pipeline_locks = summary.get("pipeline_locks", {}) if isinstance(summary.get("pipeline_locks"), dict) else {}
    write_rate = summary.get("raw_metric_write_rate", {}) if isinstance(summary.get("raw_metric_write_rate"), dict) else {}

    database_status = normalize_status_label(summary.get("database"))
    scheduler_status = "Degraded" if operational_alerts else "Up"
    running_jobs = int(scheduler_frame["is_running"].sum()) if not scheduler_frame.empty and "is_running" in scheduler_frame else 0
    failing_jobs = (
        int((pd.to_numeric(scheduler_frame["consecutive_failures"], errors="coerce").fillna(0) > 0).sum())
        if not scheduler_frame.empty and "consecutive_failures" in scheduler_frame
        else 0
    )
    stale_jobs = (
        int((scheduler_health_frame["state"] == "Stale").sum())
        if not scheduler_health_frame.empty and "state" in scheduler_health_frame
        else 0
    )
    max_lag_seconds = (
        float(scheduler_health_frame["schedule_lag_seconds"].max())
        if not scheduler_health_frame.empty and scheduler_health_frame["schedule_lag_seconds"].notna().any()
        else 0.0
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
            ("Job Stale", stale_jobs, None),
            ("Lag Terbesar", f"{max_lag_seconds:.0f} dtk", None),
        ],
        columns_per_row=4,
    )

    st.markdown("### Kapasitas dan Antrian")
    st.caption("Counter lock adalah observasi proses backend ini; scheduler memakai advisory lock MySQL terpisah.")
    render_kpi_cards(
        [
            ("DB Pool Dipakai", f"{database_pool.get('checked_out', '—')} / {database_pool.get('capacity', '—')}", None),
            ("DB Pool Overflow", int(database_pool.get("overflow") or 0), None),
            ("Job Tertinggal", int(scheduler_queue.get("lagging_jobs") or 0), None),
            ("Misfire Tercatat", int(scheduler_queue.get("misfire_count") or 0), None),
            ("Lock Contention", int(pipeline_locks.get("contention_count") or 0), None),
            ("Metric / Menit", f"{float(write_rate.get('per_minute_last_hour') or 0):.2f}", None),
            ("Metric 1 Menit", int(write_rate.get("last_minute") or 0), None),
            ("Metric 1 Jam", int(write_rate.get("last_hour") or 0), None),
        ],
        columns_per_row=4,
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
        render_paginated_dataframe(
            alert_view,
            key="system_health_operational_alerts_table",
            label="Operational Alert",
            width="stretch",
            hide_index=True,
        )

    if not scheduler_health_frame.empty:
        scheduler_health_view = scheduler_health_frame[
            [
                "job_name",
                "state",
                "expected_interval_seconds",
                "heartbeat_age_seconds",
                "schedule_lag_seconds",
                "stale_after_seconds",
                "last_heartbeat_at_wib",
                "last_duration_ms",
            ]
        ].rename(
            columns={
                "job_name": "Job",
                "state": "Status",
                "expected_interval_seconds": "Interval (dtk)",
                "heartbeat_age_seconds": "Umur Heartbeat (dtk)",
                "schedule_lag_seconds": "Lag (dtk)",
                "stale_after_seconds": "Batas Stale (dtk)",
                "last_heartbeat_at_wib": "Heartbeat Terakhir (WIB)",
                "last_duration_ms": "Durasi Terakhir (ms)",
            }
        )
        render_section_header_with_download(
            "Scheduler Timing",
            scheduler_health_view,
            file_name="system_health_scheduler_timing.csv",
            key="download_system_health_scheduler_timing",
        )
        st.caption("Lag adalah umur heartbeat di atas interval job. Status stale mengikuti `SCHEDULER_JOB_STALE_FACTOR`.")
        render_paginated_dataframe(
            scheduler_health_view,
            key="system_health_scheduler_timing_table",
            label="Scheduler Timing",
            width="stretch",
            hide_index=True,
        )

    if collector_health_frame.empty:
        st.markdown("### Kesehatan Collector")
        st.info("Belum ada metric status collector dalam 24 jam terakhir.")
    else:
        collector_view = collector_health_frame[["collector", "site", "device_type", "protocol", "state", "success_rate_percent", "sample_count", "timeout_count", "unsupported_oid_count", "last_checked_at_wib", "action"]].rename(columns={"collector": "Collector", "site": "Site", "device_type": "Tipe Device", "protocol": "Protocol", "state": "Status", "success_rate_percent": "Success Rate (%)", "sample_count": "Sampel", "timeout_count": "Timeout", "unsupported_oid_count": "OID Tidak Didukung", "last_checked_at_wib": "Check Terakhir (WIB)", "action": "Tindakan"})
        render_section_header_with_download("Kesehatan Collector", collector_view, file_name="system_health_collectors.csv", key="download_system_health_collectors")
        st.caption(f"Agregasi {int(summary.get('collector_health_window_hours', 24) or 24)} jam terakhir dari metric status collector.")
        render_paginated_dataframe(collector_view, key="system_health_collectors_table", label="Kesehatan Collector", width="stretch", hide_index=True)

    st.markdown("### Performa Collector (24 Jam)")
    if collector_runs_frame.empty:
        st.info("Belum ada telemetry eksekusi collector. Jalankan satu monitoring cycle setelah migration.")
    else:
        collector_runs_frame["success_rate_percent"] = (collector_runs_frame["successful_runs"] / collector_runs_frame["runs"] * 100).round(2)
        collector_runs_frame["last_checked_at"] = to_wib_timestamp(collector_runs_frame["last_checked_at"])
        collector_runs_frame["last_checked_at"] = collector_runs_frame["last_checked_at"].apply(format_wib_timestamp)
        collector_run_view = collector_runs_frame[["collector", "runs", "success_rate_percent", "average_duration_ms", "max_duration_ms", "metric_writes", "last_checked_at"]].rename(columns={"collector": "Collector", "runs": "Run", "success_rate_percent": "Success Rate (%)", "average_duration_ms": "Rata-rata (ms)", "max_duration_ms": "Maksimum (ms)", "metric_writes": "Metric Ditulis", "last_checked_at": "Run Terakhir (WIB)"})
        render_section_header_with_download("Performa Collector", collector_run_view, file_name="system_health_collector_runs.csv", key="download_system_health_collector_runs")
        render_paginated_dataframe(collector_run_view, key="system_health_collector_runs_table", label="Performa Collector", width="stretch", hide_index=True)

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
        render_paginated_dataframe(
            scheduler_view,
            key="system_health_scheduler_jobs_table",
            label="Scheduler Job",
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
        render_paginated_dataframe(
            freshness_view,
            key="system_health_freshness_table",
            label="Freshness",
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
        render_paginated_dataframe(
            auth_frame,
            key="system_health_auth_table",
            label="Auth",
            width="stretch",
            hide_index=True,
        )

    with runtime_col:
        st.markdown("### Runtime")
        runtime_frame = pd.DataFrame(
            [(str(key), str(value)) for key, value in sorted(runtime.items())],
            columns=["Key", "Value"],
        )
        if runtime_frame.empty:
            st.info("Runtime info belum tersedia dari backend.")
        else:
            render_paginated_dataframe(
                runtime_frame,
                key="system_health_runtime_table",
                label="Runtime",
                width="stretch",
                hide_index=True,
            )


render_live_section(auto_refresh, interval_seconds, _render_system_health_body)
