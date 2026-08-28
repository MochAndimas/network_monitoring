"""Streamlit dashboard helpers for 7 Thresholds."""

from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from components.auth import is_admin, require_dashboard_login
from components.api import delete_json, get_json, has_pending_action, post_json, put_json
from components.sidebar import collapse_sidebar_on_page_load
from components.ui import render_kpi_cards, render_paginated_dataframe, render_page_header

st.set_page_config(page_title="Thresholds", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()

render_page_header(
    "Thresholds",
    "Parameter ambang alert untuk setiap metrik monitoring.",
)
thresholds = get_json("/thresholds", [])
threshold_overrides = get_json("/thresholds/overrides", [])
maintenance_windows = get_json("/thresholds/maintenance-windows", [])


def _threshold_category(key: str) -> str:
    """Return threshold category for threshold configuration."""
    normalized = str(key or "").strip()
    if not normalized:
        return "uncategorized"
    if "_" in normalized:
        return normalized.split("_", 1)[0]
    if ":" in normalized:
        return normalized.split(":", 1)[0]
    return "general"


global_tab, overrides_tab, maintenance_tab = st.tabs(["Global", "Overrides", "Maintenance"])

with global_tab:
 if thresholds:
    dataframe = pd.DataFrame(thresholds)
    dataframe["key"] = dataframe["key"].astype(str)
    dataframe["value"] = pd.to_numeric(dataframe["value"], errors="coerce")
    dataframe["category"] = dataframe["key"].map(_threshold_category)

    filter_col1, filter_col2 = st.columns([1, 2])
    selected_category = filter_col1.selectbox(
        "Kategori",
        options=["All"] + sorted(dataframe["category"].dropna().unique().tolist()),
        index=0,
        format_func=lambda value: "Semua" if value == "All" else str(value),
    )
    search_key = filter_col2.text_input("Cari", placeholder="Cari threshold key")
    with st.expander("Filter Lanjutan"):
        sort_by = st.selectbox("Urutkan", options=["Key (A-Z)", "Nilai (Tinggi-Rendah)", "Kategori"], index=0)

    filtered_frame = dataframe.copy()
    if selected_category != "All":
        filtered_frame = filtered_frame[filtered_frame["category"] == selected_category]
    if search_key.strip():
        needle = search_key.strip().lower()
        filtered_frame = filtered_frame[filtered_frame["key"].str.lower().str.contains(needle, na=False)]

    if sort_by == "Nilai (Tinggi-Rendah)":
        filtered_frame = filtered_frame.sort_values(["value", "key"], ascending=[False, True])
    elif sort_by == "Kategori":
        filtered_frame = filtered_frame.sort_values(["category", "key"], ascending=[True, True])
    else:
        filtered_frame = filtered_frame.sort_values("key", ascending=True)

    total_thresholds = int(len(filtered_frame))
    category_count = int(filtered_frame["category"].nunique())
    avg_value = float(filtered_frame["value"].mean()) if not filtered_frame["value"].isna().all() else 0.0
    max_value = float(filtered_frame["value"].max()) if not filtered_frame["value"].isna().all() else 0.0

    render_kpi_cards(
        [
            ("Total Threshold", total_thresholds, None),
            ("Jumlah Kategori", category_count, None),
            ("Nilai Rata-rata", f"{avg_value:.2f}", None),
            ("Nilai Maksimum", f"{max_value:.2f}", None),
        ],
        columns_per_row=4,
    )

    if filtered_frame.empty:
        st.info("Tidak ada threshold yang cocok dengan filter. Ubah kategori atau kata kunci pencarian.")
    else:
        summary_frame = (
            filtered_frame.groupby("category", dropna=False)["value"]
            .agg(["count", "min", "max", "mean"])
            .reset_index()
            .rename(
                columns={
                    "category": "Kategori",
                    "count": "Jumlah Threshold",
                    "min": "Minimum",
                    "max": "Maksimum",
                    "mean": "Rata-rata",
                }
            )
            .sort_values(["Jumlah Threshold", "Kategori"], ascending=[False, True])
        )
        detail_frame = filtered_frame[["category", "key", "value"]].rename(
            columns={
                "category": "Kategori",
                "key": "Kunci Threshold",
                "value": "Nilai Saat Ini",
            }
        )
        summary_col, detail_col = st.columns([1, 2])
        with summary_col:
            st.markdown("### Ringkasan Kategori")
            category_chart = px.bar(summary_frame, x="Jumlah Threshold", y="Kategori", orientation="h", text="Jumlah Threshold", hover_data={"Rata-rata": ":.2f"})
            category_chart.update_layout(height=260, xaxis_title="Jumlah Threshold", yaxis_title="Kategori", yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(category_chart, width="stretch")
            st.dataframe(
                summary_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "Kategori": st.column_config.TextColumn("Kategori", width="small"),
                    "Jumlah Threshold": st.column_config.NumberColumn("Jumlah Threshold", format="%d", width="small"),
                    "Minimum": st.column_config.NumberColumn("Minimum", format="%.2f", width="small"),
                    "Maksimum": st.column_config.NumberColumn("Maksimum", format="%.2f", width="small"),
                    "Rata-rata": st.column_config.NumberColumn("Rata-rata", format="%.2f", width="small"),
                },
            )
        with detail_col:
            st.markdown("### Detail Threshold")
            render_paginated_dataframe(
                detail_frame,
                key="threshold_details_table",
                label="Threshold",
                width="stretch",
                hide_index=True,
                column_config={
                    "Kategori": st.column_config.TextColumn("Kategori", width="small"),
                    "Kunci Threshold": st.column_config.TextColumn("Kunci Threshold", width="large"),
                    "Nilai Saat Ini": st.column_config.NumberColumn("Nilai Saat Ini", format="%.4f", width="small"),
                },
            )

    st.markdown("### Editor Threshold")
    if not is_admin():
        st.info("Role viewer hanya dapat melihat data threshold.")
    elif filtered_frame.empty:
        st.info("Pilih filter lain untuk menampilkan threshold yang ingin diubah.")
    else:
        selected_key = st.selectbox(
            "Kunci Threshold",
            options=filtered_frame["key"].sort_values().tolist(),
            index=0,
        )
        selected_row = dataframe.loc[dataframe["key"] == selected_key].iloc[0]
        current_value = float(selected_row["value"])
        editor_col1, editor_col2 = st.columns([1, 1])
        editor_col1.metric("Nilai Saat Ini", f"{current_value:.2f}")
        updated_value = editor_col2.number_input(
            "Nilai Baru",
            value=current_value,
            step=1.0,
            format="%.4f",
        )

        update_threshold_clicked = st.button("Simpan Perubahan Threshold", width="stretch")
        if is_admin() and (update_threshold_clicked or has_pending_action("update_threshold")):
            result = put_json(
                f"/thresholds/{selected_key}",
                {"value": updated_value},
                {"key": selected_key, "value": current_value},
                action_key="update_threshold",
            )
            st.success(f"Threshold `{result['key']}` berhasil diperbarui ke nilai `{result['value']}`.")
 else:
    st.info("Belum ada threshold tersedia. Tambahkan konfigurasi threshold di backend untuk menampilkan data.")


with overrides_tab:
    st.markdown("### Threshold Overrides")
    override_frame = pd.DataFrame(threshold_overrides)
    if not override_frame.empty:
        override_frame["scope"] = override_frame.apply(
            lambda row: (
                f"device:{int(row['device_id'])}" if pd.notna(row.get("device_id")) else
                f"type:{row['device_type']}" if row.get("device_type") else
                f"site:{row['site']}" if row.get("site") else "-"
            ),
            axis=1,
        )
        override_frame["status"] = override_frame["is_active"].map(lambda value: "Active" if value else "Inactive")
        render_paginated_dataframe(
            override_frame[["id", "threshold_key", "value", "scope", "status", "description"]],
            key="threshold_overrides_table",
            label="Override",
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("Belum ada threshold override.")

    if is_admin() and thresholds:
        st.markdown("### Tambah Override")
        threshold_keys = sorted(str(item["key"]) for item in thresholds)
        ov_col1, ov_col2, ov_col3 = st.columns(3)
        override_key = ov_col1.selectbox("Threshold Key", options=threshold_keys)
        override_value = ov_col2.number_input("Nilai Override", value=0.0, step=1.0, format="%.4f")
        scope_type = ov_col3.selectbox("Scope", options=["site", "device_type", "device_id"])
        scope_value = st.text_input("Scope Value", placeholder="Contoh: HQ / mikrotik / 12")
        override_description = st.text_input("Deskripsi", placeholder="Opsional")
        if st.button("Simpan Override", key="create_threshold_override"):
            payload = {
                "threshold_key": override_key,
                "value": override_value,
                "description": override_description or None,
            }
            if scope_type == "device_id":
                payload["device_id"] = int(scope_value)
            else:
                payload[scope_type] = scope_value
            post_json("/thresholds/overrides", payload, {}, action_key="create_threshold_override")
            st.cache_data.clear()
            st.rerun()

        active_override_ids = override_frame.loc[override_frame["is_active"].eq(True), "id"].tolist() if not override_frame.empty else []
        if active_override_ids:
            selected_override_id = st.selectbox("Deactivate Override", options=active_override_ids)
            if st.button("Deactivate Override", key="deactivate_threshold_override"):
                delete_json(f"/thresholds/overrides/{int(selected_override_id)}", {}, action_key="deactivate_threshold_override")
                st.cache_data.clear()
                st.rerun()
    elif not is_admin():
        st.info("Role viewer hanya dapat melihat override.")


with maintenance_tab:
    st.markdown("### Maintenance Windows")
    window_frame = pd.DataFrame(maintenance_windows)
    if not window_frame.empty:
        window_frame["scope"] = window_frame.apply(
            lambda row: f"device:{int(row['device_id'])}" if pd.notna(row.get("device_id")) else f"site:{row.get('site') or '-'}",
            axis=1,
        )
        window_frame["status"] = window_frame["is_active"].map(lambda value: "Active" if value else "Inactive")
        render_paginated_dataframe(
            window_frame[["id", "name", "scope", "starts_at", "ends_at", "status", "reason"]],
            key="maintenance_windows_table",
            label="Maintenance",
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("Belum ada maintenance window.")

    if is_admin():
        st.markdown("### Tambah Maintenance Window")
        mw_col1, mw_col2, mw_col3 = st.columns(3)
        window_name = mw_col1.text_input("Nama Window", value="Maintenance")
        window_scope = mw_col2.selectbox("Scope", options=["site", "device_id"], key="maintenance_scope")
        window_scope_value = mw_col3.text_input("Scope Value", placeholder="Contoh: HQ / 12", key="maintenance_scope_value")
        start_default = datetime.now().replace(second=0, microsecond=0)
        end_default = start_default + timedelta(hours=1)
        time_col1, time_col2 = st.columns(2)
        starts_at = time_col1.text_input("Mulai ISO", value=start_default.isoformat(timespec="minutes"))
        ends_at = time_col2.text_input("Selesai ISO", value=end_default.isoformat(timespec="minutes"))
        reason = st.text_area("Reason", height=90)
        if st.button("Simpan Maintenance Window", key="create_maintenance_window"):
            payload = {
                "name": window_name,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "reason": reason or None,
            }
            if window_scope == "device_id":
                payload["device_id"] = int(window_scope_value)
            else:
                payload["site"] = window_scope_value
            post_json("/thresholds/maintenance-windows", payload, {}, action_key="create_maintenance_window")
            st.cache_data.clear()
            st.rerun()

        active_window_ids = window_frame.loc[window_frame["is_active"].eq(True), "id"].tolist() if not window_frame.empty else []
        if active_window_ids:
            selected_window_id = st.selectbox("Deactivate Maintenance", options=active_window_ids)
            if st.button("Deactivate Maintenance", key="deactivate_maintenance_window"):
                delete_json(f"/thresholds/maintenance-windows/{int(selected_window_id)}", {}, action_key="deactivate_maintenance_window")
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("Role viewer hanya dapat melihat maintenance window.")
