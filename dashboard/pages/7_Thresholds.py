"""Define module logic for `dashboard/pages/7_Thresholds.py`.

This module contains project-specific implementation details.
"""

import altair as alt
import pandas as pd
import streamlit as st

from components.auth import is_admin, require_dashboard_login
from components.api import get_json, has_pending_action, put_json
from components.sidebar import collapse_sidebar_on_page_load
from components.ui import render_kpi_cards, render_page_header

st.set_page_config(page_title="Thresholds", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()

render_page_header(
    "Thresholds",
    "Parameter ambang alert untuk setiap metrik monitoring.",
)
thresholds = get_json("/thresholds", [])


def _threshold_category(key: str) -> str:
    """Perform threshold category.

    Args:
        key: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    normalized = str(key or "").strip()
    if not normalized:
        return "uncategorized"
    if "_" in normalized:
        return normalized.split("_", 1)[0]
    if ":" in normalized:
        return normalized.split(":", 1)[0]
    return "general"


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
        adv_col1, adv_col2 = st.columns(2)
        sort_by = adv_col1.selectbox("Urutkan", options=["Key (A-Z)", "Nilai (Tinggi-Rendah)", "Kategori"], index=0)
        max_rows = adv_col2.selectbox("Maks. Baris Detail", options=[25, 50, 100, 200], index=2)

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
            category_chart = (
                alt.Chart(summary_frame)
                .mark_bar()
                .encode(
                    x=alt.X("Jumlah Threshold:Q", title="Jumlah Threshold"),
                    y=alt.Y("Kategori:N", sort="-x", title="Kategori"),
                    tooltip=[
                        alt.Tooltip("Kategori:N", title="Kategori"),
                        alt.Tooltip("Jumlah Threshold:Q", title="Jumlah"),
                        alt.Tooltip("Rata-rata:Q", title="Rata-rata", format=".2f"),
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(category_chart, width="stretch")
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
            st.dataframe(
                detail_frame.head(int(max_rows)),
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
