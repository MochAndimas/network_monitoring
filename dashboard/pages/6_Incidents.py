"""Streamlit dashboard helpers for 6 Incidents."""

from urllib.parse import quote_plus

import altair as alt
import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json, paged_items, paged_meta, post_json, put_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp
from components.ui import (
    normalize_status_label,
    render_csv_download,
    render_kpi_cards,
    render_meta_row,
    render_page_header,
    status_priority,
)

SEVERITY_OPTIONS = ["", "critical", "high", "warning", "info"]

st.set_page_config(page_title="Incidents", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()
render_page_header(
    "Incidents",
    "Pelacakan insiden aktif dan selesai untuk evaluasi dampak operasional.",
)

filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])
status_filter = filter_col1.selectbox(
    "Status Insiden",
    options=["All", "active", "resolved"],
    index=0,
    format_func=lambda value: "Semua" if value == "All" else normalize_status_label(str(value)),
)
site_filter = filter_col2.text_input("Site", placeholder="Kosongkan untuk semua site")
search_filter = filter_col3.text_input("Cari", placeholder="Filter berdasarkan device atau ringkasan")
with st.expander("Filter Lanjutan"):
    adv_col1, adv_col2, adv_col3 = st.columns(3)
    sort_mode = adv_col1.selectbox("Urutkan", options=["Terbaru", "Durasi Terpanjang", "Berdasarkan Status"], index=0)
    max_rows = adv_col2.selectbox("Maks. Baris Detail", options=[25, 50, 100, 200], index=1)
    incidents_page_size = adv_col3.selectbox("Baris per Halaman", options=[25, 50, 100, 200], index=1)
auto_refresh, interval_seconds = refresh_controls("incidents", default_enabled=True, default_interval=15)
incidents_page_key = "incidents_page"
incidents_filter_signature_key = "incidents_filter_signature"
incidents_filter_signature = (
    str(status_filter),
    site_filter.strip().lower(),
    search_filter.strip().lower(),
    str(sort_mode),
    int(incidents_page_size),
)
if st.session_state.get(incidents_filter_signature_key) != incidents_filter_signature:
    st.session_state[incidents_page_key] = 1
    st.session_state[incidents_filter_signature_key] = incidents_filter_signature
current_incidents_page = max(int(st.session_state.get(incidents_page_key, 1) or 1), 1)
incidents_offset = (current_incidents_page - 1) * int(incidents_page_size)


def _duration_label(minutes_value: float | None) -> str:
    """Return duration label for incident tracking."""
    if minutes_value is None or pd.isna(minutes_value):
        return "-"
    minutes = int(minutes_value)
    hours, mins = divmod(minutes, 60)
    return f"{hours}j {mins}m" if hours else f"{mins}m"


def _render_incident_detail(row: pd.Series) -> None:
    """Render the full detail for one incident selected from the compact table."""
    incident_id = int(row["ID"])
    st.markdown(f"#### Detail Insiden #{incident_id}")
    render_meta_row(
        [
            ("Mulai", str(row.get("Mulai (WIB)") or "-")),
            ("Selesai", str(row.get("Selesai (WIB)") or "-")),
            ("Acknowledged", str(row.get("Ack (WIB)") or "-")),
            ("Owner", str(row.get("Owner") or "-")),
            ("Assignee", str(row.get("Assignee") or "-")),
        ]
    )
    st.caption("Ringkasan")
    st.write(str(row.get("Ringkasan") or "-"))


def _render_detail_table(dataframe: pd.DataFrame) -> None:
    """Render a compact selectable table and the selected incident detail."""
    if dataframe.empty:
        return

    compact_frame = dataframe[
        ["Waktu", "Nama Device", "Site", "Severity", "Durasi", "Status", "Ringkasan"]
    ].rename(columns={"Nama Device": "Device"})
    table_key = (
        f"incidents_compact_detail_table_{int(dataframe.iloc[0]['ID'])}_"
        f"{int(dataframe.iloc[-1]['ID'])}_{len(dataframe)}"
    )
    table_event = st.dataframe(
        compact_frame,
        width="stretch",
        hide_index=True,
        height=min(38 + len(compact_frame) * 40, 438),
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
        column_config={
            "Waktu": st.column_config.TextColumn("Waktu", width=110),
            "Device": st.column_config.TextColumn("Device", width=155),
            "Site": st.column_config.TextColumn("Site", width=110),
            "Severity": st.column_config.TextColumn("Severity", width=80),
            "Durasi": st.column_config.TextColumn("Durasi", width=65),
            "Status": st.column_config.TextColumn("Status", width=90),
            "Ringkasan": st.column_config.TextColumn("Ringkasan", width=350),
        },
    )
    selected_rows = list(table_event.selection.rows)
    if selected_rows:
        _render_incident_detail(dataframe.iloc[int(selected_rows[0])])


def _render_detail_table_controls(
    dataframe: pd.DataFrame,
    *,
    title: str,
    page_size: int = 10,
) -> pd.DataFrame:
    """Return one page of incident detail rows for a compact table display."""
    if dataframe.empty:
        return dataframe
    page_size = max(int(page_size), 1)
    total_rows = int(len(dataframe))
    total_pages = max((total_rows - 1) // page_size + 1, 1)
    page_key = "incidents_detail_table_page"
    current_page = min(max(int(st.session_state.get(page_key, 1) or 1), 1), total_pages)
    if st.session_state.get(page_key) != current_page:
        st.session_state[page_key] = current_page

    title_col, control_col, caption_col, download_col = st.columns([2, 1, 3, 1])
    title_col.markdown(f"### {title}")
    if total_rows > page_size:
        current_page = int(
            control_col.number_input(
                "Halaman Detail",
                min_value=1,
                max_value=total_pages,
                value=current_page,
                step=1,
                key=page_key,
            )
        )
        start_row = (current_page - 1) * page_size + 1
        end_row = min(current_page * page_size, total_rows)
        caption_col.caption(f"Menampilkan detail {start_row}-{end_row} dari {total_rows} baris terpilih.")
    else:
        caption_col.caption(f"Menampilkan semua {total_rows} baris terpilih.")

    with download_col:
        render_csv_download(
            "Download CSV",
            dataframe,
            file_name="incidents.csv",
            key="download_incidents",
        )

    start_index = (current_page - 1) * page_size
    return dataframe.iloc[start_index : start_index + page_size]


def _incident_option_label(row: pd.Series) -> str:
    """Return a compact incident selector label."""
    status = str(row.get("status") or "-")
    device = str(row.get("device_name") or "-")
    severity = str(row.get("effective_severity") or "-")
    started = str(row.get("started_at_wib") or "-")
    return f"#{int(row['id'])} | {status} | {severity} | {device} | {started}"


def _render_timeline(incident_id: int) -> None:
    """Render one incident timeline."""
    timeline_payload = get_json(f"/incidents/{incident_id}/timeline", {"items": []})
    timeline_items = timeline_payload.get("items", []) if isinstance(timeline_payload, dict) else []
    st.markdown("### Timeline")
    if not timeline_items:
        st.info("Timeline belum punya event.")
        return
    timeline_frame = pd.DataFrame(timeline_items)
    timeline_frame["created_at"] = to_wib_timestamp(timeline_frame["created_at"])
    timeline_frame["Waktu (WIB)"] = timeline_frame["created_at"].apply(format_wib_timestamp)
    timeline_frame["Event"] = timeline_frame["event_type"].astype(str).str.replace("_", " ").str.title()
    timeline_frame["Actor"] = timeline_frame["actor"].fillna("-")
    timeline_frame["Pesan"] = timeline_frame["message"].fillna("-")
    st.dataframe(
        timeline_frame[["Waktu (WIB)", "Event", "Actor", "Pesan"]],
        width="stretch",
        hide_index=True,
        column_config={
            "Waktu (WIB)": st.column_config.TextColumn("Waktu (WIB)", width="medium"),
            "Event": st.column_config.TextColumn("Event", width="small"),
            "Actor": st.column_config.TextColumn("Actor", width="small"),
            "Pesan": st.column_config.TextColumn("Pesan", width="large"),
        },
    )


def _render_escalations() -> None:
    """Render active incident escalations."""
    escalation_payload = get_json("/incidents/escalations", {"items": []})
    escalation_items = escalation_payload.get("items", []) if isinstance(escalation_payload, dict) else []
    st.markdown("### Escalation")
    if not escalation_items:
        st.success("Tidak ada critical/high incident yang melewati window escalation.")
        return
    escalation_frame = pd.DataFrame(escalation_items)
    escalation_frame["started_at"] = to_wib_timestamp(escalation_frame["started_at"])
    escalation_frame["Mulai (WIB)"] = escalation_frame["started_at"].apply(format_wib_timestamp)
    escalation_frame["Severity"] = escalation_frame["effective_severity"].fillna("-").astype(str).str.title()
    escalation_frame["Device"] = escalation_frame["device_name"].fillna("-")
    escalation_frame["Assignee"] = escalation_frame["assignee"].fillna("-")
    escalation_frame["Ringkasan"] = escalation_frame["summary"].fillna("-")
    st.dataframe(
        escalation_frame[["Mulai (WIB)", "Severity", "Device", "Assignee", "Ringkasan"]],
        width="stretch",
        hide_index=True,
        column_config={
            "Mulai (WIB)": st.column_config.TextColumn("Mulai (WIB)", width="medium"),
            "Severity": st.column_config.TextColumn("Severity", width="small"),
            "Device": st.column_config.TextColumn("Device", width="medium"),
            "Assignee": st.column_config.TextColumn("Assignee", width="medium"),
            "Ringkasan": st.column_config.TextColumn("Ringkasan", width="large"),
        },
    )


def _render_workflow_panel(dataframe: pd.DataFrame) -> None:
    """Render incident workflow actions and timeline."""
    st.markdown("### Workflow Insiden")
    required_columns = {"id", "raw_status"}
    if dataframe.empty or not required_columns.issubset(dataframe.columns):
        st.info("Tidak ada insiden aktif yang memerlukan tindakan workflow.")
        return

    active_frame = dataframe.loc[dataframe["raw_status"].fillna("").str.lower().eq("active")].copy()
    if active_frame.empty:
        st.info("Tidak ada insiden aktif yang memerlukan tindakan workflow.")
        return

    options = active_frame.sort_values("started_at", ascending=False)["id"].tolist()
    selectbox_key = "incident_workflow_selected_id"
    if st.session_state.get(selectbox_key) not in options:
        st.session_state[selectbox_key] = options[0]
    selected_id = st.selectbox(
        "Pilih Incident",
        options=options,
        format_func=lambda incident_id: _incident_option_label(
            active_frame.loc[active_frame["id"] == incident_id].iloc[0]
        ),
        key=selectbox_key,
    )
    selected = active_frame.loc[active_frame["id"] == selected_id].iloc[0]
    workflow_col, action_col = st.columns([2, 1])
    with workflow_col:
        owner = st.text_input("Owner", value=str(selected.get("owner") or ""), key=f"incident_owner_{selected_id}")
        assignee = st.text_input("Assignee", value=str(selected.get("assignee") or ""), key=f"incident_assignee_{selected_id}")
        current_severity = str(selected.get("severity_override") or "")
        severity_index = SEVERITY_OPTIONS.index(current_severity) if current_severity in SEVERITY_OPTIONS else 0
        severity_override = st.selectbox(
            "Severity Override",
            options=SEVERITY_OPTIONS,
            index=severity_index,
            format_func=lambda value: "Ikuti alert" if not value else value.title(),
            key=f"incident_severity_{selected_id}",
        )
        note = st.text_area("Note", value=str(selected.get("note") or ""), key=f"incident_note_{selected_id}", height=120)
        if st.button("Simpan Workflow", key=f"incident_save_{selected_id}", type="primary"):
            put_json(
                f"/incidents/{selected_id}/workflow",
                {"owner": owner, "assignee": assignee, "severity_override": severity_override or None, "note": note},
                {},
                action_key=f"incident_workflow_{selected_id}",
            )
            st.cache_data.clear()
            st.rerun()
    with action_col:
        st.caption(f"Status: {selected.get('status') or '-'}")
        st.caption(f"Ack: {selected.get('acknowledged_by') or '-'}")
        action_note = st.text_area("Action Note", key=f"incident_action_note_{selected_id}", height=100)
        if pd.isna(selected.get("acknowledged_at")) or not selected.get("acknowledged_at"):
            if st.button("Acknowledge", key=f"incident_ack_{selected_id}"):
                post_json(
                    f"/incidents/{selected_id}/ack",
                    {"note": action_note, "assignee": assignee},
                    {},
                    action_key=f"incident_ack_{selected_id}",
                )
                st.cache_data.clear()
                st.rerun()
        if str(selected.get("raw_status") or "").lower() == "active":
            if st.button("Resolve", key=f"incident_resolve_{selected_id}"):
                post_json(
                    f"/incidents/{selected_id}/resolve",
                    {"note": action_note},
                    {},
                    action_key=f"incident_resolve_{selected_id}",
                )
                st.cache_data.clear()
                st.rerun()
        else:
            if st.button("Reopen", key=f"incident_reopen_{selected_id}"):
                post_json(
                    f"/incidents/{selected_id}/reopen",
                    {"note": action_note},
                    {},
                    action_key=f"incident_reopen_{selected_id}",
                )
                st.cache_data.clear()
                st.rerun()
    _render_timeline(int(selected_id))


def _render_incidents_body() -> None:
    """Render incidents body for the dashboard UI."""
    path = f"/incidents/paged?limit={int(incidents_page_size)}&offset={incidents_offset}"
    if status_filter != "All":
        path = f"{path}&status={status_filter}"
    if site_filter.strip():
        path = f"{path}&site={quote_plus(site_filter.strip())}"
    normalized_search_filter = search_filter.strip()
    if normalized_search_filter:
        path = f"{path}&search={quote_plus(normalized_search_filter)}"
    incidents_payload = get_json(
        path,
        {"items": [], "meta": {"total": 0, "limit": int(incidents_page_size), "offset": incidents_offset}},
    )
    incidents = paged_items(incidents_payload, [])
    incidents_meta = paged_meta(incidents_payload)
    incidents_total = int(incidents_meta.get("total") or 0)
    incidents_total_pages = max((incidents_total - 1) // int(incidents_page_size) + 1, 1)
    if current_incidents_page > incidents_total_pages:
        st.session_state[incidents_page_key] = incidents_total_pages
        st.rerun()
    start_row = 0 if incidents_total == 0 else incidents_offset + 1
    end_row = min(incidents_offset + len(incidents), incidents_total)

    render_meta_row(
        [
            ("Refresh Otomatis", live_status_text(auto_refresh, interval_seconds)),
            ("Terakhir Diperbarui", rendered_at_label()),
            ("Filter Status", normalize_status_label(status_filter)),
            ("Filter Site", site_filter.strip() or "Semua"),
            ("Urutan", sort_mode),
            ("Cakupan Data", f"{start_row}-{end_row} / {incidents_total} incidents"),
        ]
    )
    page_col, page_meta_col = st.columns([1, 4])
    page_col.number_input(
        "Halaman Incidents",
        min_value=1,
        max_value=incidents_total_pages,
        value=min(current_incidents_page, incidents_total_pages),
        step=1,
        key=incidents_page_key,
    )
    page_meta_col.caption(f"Menampilkan {start_row}-{end_row} dari {incidents_total} incidents.")

    if not incidents:
        st.info("Belum ada insiden tercatat. Data akan muncul setelah gangguan terdeteksi.")
        return

    dataframe = pd.DataFrame(incidents)
    dataframe["device_name"] = dataframe["device_name"].fillna("-") if "device_name" in dataframe.columns else "-"
    dataframe["site"] = dataframe["site"].fillna("-") if "site" in dataframe.columns else "-"
    dataframe["summary"] = dataframe["summary"].fillna("-") if "summary" in dataframe.columns else "-"
    dataframe["owner"] = dataframe["owner"].fillna("") if "owner" in dataframe.columns else ""
    dataframe["assignee"] = dataframe["assignee"].fillna("") if "assignee" in dataframe.columns else ""
    dataframe["severity_override"] = dataframe["severity_override"].fillna("") if "severity_override" in dataframe.columns else ""
    dataframe["effective_severity"] = dataframe["effective_severity"].fillna("") if "effective_severity" in dataframe.columns else ""
    dataframe["note"] = dataframe["note"].fillna("") if "note" in dataframe.columns else ""
    dataframe["acknowledged_by"] = dataframe["acknowledged_by"].fillna("") if "acknowledged_by" in dataframe.columns else ""
    if "status" in dataframe.columns:
        dataframe["raw_status"] = dataframe["status"].astype(str)
        dataframe["status"] = dataframe["status"].map(normalize_status_label)
    else:
        dataframe["raw_status"] = "unknown"
        dataframe["status"] = "Unknown"
    dataframe["status_priority"] = dataframe["status"].map(status_priority)

    if "started_at" in dataframe.columns:
        dataframe["started_at"] = to_wib_timestamp(dataframe["started_at"])
        dataframe["started_at_wib"] = dataframe["started_at"].apply(format_wib_timestamp)
        dataframe["started_at_short"] = dataframe["started_at"].apply(
            lambda value: value.strftime("%d-%m %H:%M") if pd.notna(value) else "-"
        )
    else:
        dataframe["started_at"] = pd.NaT
        dataframe["started_at_wib"] = "-"
        dataframe["started_at_short"] = "-"

    if "ended_at" in dataframe.columns:
        dataframe["ended_at"] = to_wib_timestamp(dataframe["ended_at"])
        dataframe["ended_at_wib"] = dataframe["ended_at"].apply(format_wib_timestamp)
    else:
        dataframe["ended_at"] = pd.NaT
        dataframe["ended_at_wib"] = "-"

    if "acknowledged_at" in dataframe.columns:
        dataframe["acknowledged_at"] = to_wib_timestamp(dataframe["acknowledged_at"])
        dataframe["acknowledged_at_wib"] = dataframe["acknowledged_at"].apply(format_wib_timestamp)
    else:
        dataframe["acknowledged_at"] = pd.NaT
        dataframe["acknowledged_at_wib"] = "-"

    dataframe["duration_minutes"] = (
        (dataframe["ended_at"] - dataframe["started_at"]).dt.total_seconds().div(60)
        if "ended_at" in dataframe.columns and "started_at" in dataframe.columns
        else pd.Series(dtype=float)
    )
    dataframe["duration_label"] = dataframe["duration_minutes"].map(_duration_label)

    filtered_frame = dataframe.copy()

    if filtered_frame.empty:
        st.info("Tidak ada insiden yang cocok dengan filter. Coba ubah kata kunci pencarian.")
        return

    if sort_mode == "Berdasarkan Status":
        filtered_frame = filtered_frame.sort_values(["status_priority", "started_at"], ascending=[True, False])
    elif sort_mode == "Durasi Terpanjang":
        filtered_frame = filtered_frame.sort_values(["duration_minutes", "started_at"], ascending=[False, False])
    else:
        filtered_frame = filtered_frame.sort_values("started_at", ascending=False)

    total_incidents = int(len(filtered_frame))
    active_incidents = int(filtered_frame["raw_status"].str.lower().eq("active").sum())
    resolved_incidents = int(filtered_frame["raw_status"].str.lower().eq("resolved").sum())
    acknowledged_incidents = int(filtered_frame["acknowledged_at"].notna().sum())
    affected_devices = int(filtered_frame["device_name"].nunique())

    duration_series = filtered_frame["duration_minutes"].dropna()
    median_duration_label = _duration_label(duration_series.median() if not duration_series.empty else None)

    render_kpi_cards(
        [
            ("Total Insiden", total_incidents, None),
            ("Insiden Aktif", active_incidents, None),
            ("Insiden Selesai", resolved_incidents, None),
            ("Sudah Ack", acknowledged_incidents, None),
            ("Device Terdampak", affected_devices, None),
            ("Durasi Median", median_duration_label, None),
        ],
        columns_per_row=6,
    )

    detail_columns = [
        "id",
        "started_at_wib",
        "started_at_short",
        "ended_at_wib",
        "acknowledged_at_wib",
        "duration_label",
        "device_name",
        "site",
        "effective_severity",
        "owner",
        "assignee",
        "status",
        "summary",
    ]
    detail_frame = filtered_frame[detail_columns].rename(
        columns={
            "id": "ID",
            "started_at_wib": "Mulai (WIB)",
            "started_at_short": "Waktu",
            "ended_at_wib": "Selesai (WIB)",
            "acknowledged_at_wib": "Ack (WIB)",
            "duration_label": "Durasi",
            "device_name": "Nama Device",
            "site": "Site",
            "effective_severity": "Severity",
            "owner": "Owner",
            "assignee": "Assignee",
            "status": "Status",
            "summary": "Ringkasan",
        }
    )
    capped_detail_frame = detail_frame.head(int(max_rows))

    analytics_tab, workflow_tab = st.tabs(["Analytics", "Workflow"])
    with analytics_tab:
        _render_incident_analytics(filtered_frame)
        _render_detail_table(_render_detail_table_controls(capped_detail_frame, title="Detail Insiden", page_size=10))
        st.markdown("")
        st.caption("Tip: gunakan urutan Durasi Terpanjang untuk meninjau insiden dengan dampak waktu terbesar.")
    with workflow_tab:
        _render_escalations()
        _render_workflow_panel(filtered_frame)


def _render_incident_analytics(filtered_frame: pd.DataFrame) -> None:
    """Render incident analytics charts and compact tables."""

    status_counts = (
        filtered_frame["status"]
        .value_counts()
        .rename_axis("Status")
        .reset_index(name="Jumlah")
    )
    status_counts["Priority"] = status_counts["Status"].map(status_priority)
    status_counts = status_counts.sort_values(["Priority", "Jumlah", "Status"], ascending=[True, False, True])
    top_devices = (
        filtered_frame["device_name"]
        .value_counts()
        .rename_axis("Nama Device")
        .reset_index(name="Jumlah Insiden")
        .sort_values("Jumlah Insiden", ascending=False)
        .head(10)
    )

    summary_col, top_col = st.columns([1, 1])
    with summary_col:
        st.markdown("### Distribusi Status Insiden")
        status_chart = (
            alt.Chart(status_counts)
            .mark_bar()
            .encode(
                x=alt.X("Jumlah:Q", title="Jumlah Insiden"),
                y=alt.Y("Status:N", sort="-x", title="Status"),
                tooltip=[alt.Tooltip("Status:N", title="Status"), alt.Tooltip("Jumlah:Q", title="Jumlah")],
            )
            .properties(height=260)
        )
        st.altair_chart(status_chart, width="stretch")
        st.dataframe(
            status_counts[["Status", "Jumlah"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
            },
        )
    with top_col:
        st.markdown("### Device Paling Terdampak")
        device_chart = (
            alt.Chart(top_devices)
            .mark_bar()
            .encode(
                x=alt.X("Jumlah Insiden:Q", title="Jumlah Insiden"),
                y=alt.Y("Nama Device:N", sort="-x", title="Nama Device"),
                tooltip=[alt.Tooltip("Nama Device:N", title="Nama Device"), alt.Tooltip("Jumlah Insiden:Q", title="Jumlah")],
            )
            .properties(height=260)
        )
        st.altair_chart(device_chart, width="stretch")
        st.dataframe(
            top_devices,
            width="stretch",
            hide_index=True,
            column_config={
                "Nama Device": st.column_config.TextColumn("Nama Device", width="large"),
                "Jumlah Insiden": st.column_config.NumberColumn("Jumlah Insiden", width="small", format="%d"),
            },
        )


render_live_section(auto_refresh, interval_seconds, _render_incidents_body)
