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
    "Parameter ambang alerting untuk setiap metrik utama pada monitoring.",
)
thresholds = get_json("/thresholds", [])


def _threshold_category(key: str) -> str:
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
        "Category",
        options=["All"] + sorted(dataframe["category"].dropna().unique().tolist()),
        index=0,
    )
    search_key = filter_col2.text_input("Cari", placeholder="Cari threshold key")
    with st.expander("Filter Lanjutan"):
        adv_col1, adv_col2 = st.columns(2)
        sort_by = adv_col1.selectbox("Urutkan", options=["Key (A-Z)", "Value (High-Low)", "Category"], index=0)
        max_rows = adv_col2.selectbox("Maks. Baris Detail", options=[25, 50, 100, 200], index=2)

    filtered_frame = dataframe.copy()
    if selected_category != "All":
        filtered_frame = filtered_frame[filtered_frame["category"] == selected_category]
    if search_key.strip():
        needle = search_key.strip().lower()
        filtered_frame = filtered_frame[filtered_frame["key"].str.lower().str.contains(needle, na=False)]

    if sort_by == "Value (High-Low)":
        filtered_frame = filtered_frame.sort_values(["value", "key"], ascending=[False, True])
    elif sort_by == "Category":
        filtered_frame = filtered_frame.sort_values(["category", "key"], ascending=[True, True])
    else:
        filtered_frame = filtered_frame.sort_values("key", ascending=True)

    total_thresholds = int(len(filtered_frame))
    category_count = int(filtered_frame["category"].nunique())
    avg_value = float(filtered_frame["value"].mean()) if not filtered_frame["value"].isna().all() else 0.0
    max_value = float(filtered_frame["value"].max()) if not filtered_frame["value"].isna().all() else 0.0

    render_kpi_cards(
        [
            ("Thresholds", total_thresholds, None),
            ("Categories", category_count, None),
            ("Average Value", f"{avg_value:.2f}", None),
            ("Max Value", f"{max_value:.2f}", None),
        ],
        columns_per_row=4,
    )

    if filtered_frame.empty:
        st.info("Tidak ada threshold yang cocok dengan filter saat ini.")
    else:
        summary_frame = (
            filtered_frame.groupby("category", dropna=False)["value"]
            .agg(["count", "min", "max", "mean"])
            .reset_index()
            .rename(
                columns={
                    "category": "Category",
                    "count": "Threshold Count",
                    "min": "Min",
                    "max": "Max",
                    "mean": "Average",
                }
            )
            .sort_values(["Threshold Count", "Category"], ascending=[False, True])
        )
        detail_frame = filtered_frame[["category", "key", "value"]].rename(
            columns={
                "category": "Category",
                "key": "Threshold Key",
                "value": "Current Value",
            }
        )
        summary_col, detail_col = st.columns([1, 2])
        with summary_col:
            st.markdown("### Category Summary")
            category_chart = (
                alt.Chart(summary_frame)
                .mark_bar()
                .encode(
                    x=alt.X("Threshold Count:Q", title="Threshold Count"),
                    y=alt.Y("Category:N", sort="-x", title="Category"),
                    tooltip=[
                        alt.Tooltip("Category:N", title="Category"),
                        alt.Tooltip("Threshold Count:Q", title="Thresholds"),
                        alt.Tooltip("Average:Q", title="Average", format=".2f"),
                    ],
                )
                .properties(height=240)
            )
            st.altair_chart(category_chart, width="stretch")
            st.dataframe(
                summary_frame,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Category": st.column_config.TextColumn("Category", width="small"),
                    "Threshold Count": st.column_config.NumberColumn("Threshold Count", format="%d", width="small"),
                    "Min": st.column_config.NumberColumn("Min", format="%.2f", width="small"),
                    "Max": st.column_config.NumberColumn("Max", format="%.2f", width="small"),
                    "Average": st.column_config.NumberColumn("Average", format="%.2f", width="small"),
                },
            )
        with detail_col:
            st.markdown("### Threshold Details")
            st.dataframe(
                detail_frame.head(int(max_rows)),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Category": st.column_config.TextColumn("Category", width="small"),
                    "Threshold Key": st.column_config.TextColumn("Threshold Key", width="large"),
                    "Current Value": st.column_config.NumberColumn("Current Value", format="%.4f", width="small"),
                },
            )

    st.markdown("### Threshold Editor")
    if not is_admin():
        st.info("Role viewer hanya bisa melihat threshold.")
    elif filtered_frame.empty:
        st.info("Pilih filter lain untuk mengedit threshold.")
    else:
        selected_key = st.selectbox(
            "Threshold key",
            options=filtered_frame["key"].sort_values().tolist(),
            index=0,
        )
        selected_row = dataframe.loc[dataframe["key"] == selected_key].iloc[0]
        current_value = float(selected_row["value"])
        editor_col1, editor_col2 = st.columns([1, 1])
        editor_col1.metric("Current Value", f"{current_value:.2f}")
        updated_value = editor_col2.number_input(
            "New value",
            value=current_value,
            step=1.0,
            format="%.4f",
        )

        update_threshold_clicked = st.button("Update Threshold", use_container_width=True)
        if is_admin() and (update_threshold_clicked or has_pending_action("update_threshold")):
            result = put_json(
                f"/thresholds/{selected_key}",
                {"value": updated_value},
                {"key": selected_key, "value": current_value},
                action_key="update_threshold",
            )
            st.success(f"Threshold {result['key']} updated to {result['value']}.")
else:
    st.info("Belum ada threshold yang tersedia.")
