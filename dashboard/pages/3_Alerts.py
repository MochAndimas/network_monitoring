import pandas as pd
import streamlit as st

from components.api import get_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp

st.set_page_config(page_title="Alerts", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()


def _render_alerts_body() -> None:
    alerts = get_json("/alerts/active", [])
    st.caption(f"Render terakhir: {rendered_at_label()}")

    if alerts:
        dataframe = pd.DataFrame(alerts)
        if "created_at" in dataframe.columns:
            dataframe["created_at"] = to_wib_timestamp(dataframe["created_at"])
            dataframe["created_at"] = dataframe["created_at"].apply(format_wib_timestamp)
        if "resolved_at" in dataframe.columns:
            dataframe["resolved_at"] = to_wib_timestamp(dataframe["resolved_at"])
            dataframe["resolved_at"] = dataframe["resolved_at"].apply(format_wib_timestamp)
        severity_counts = dataframe["severity"].value_counts().rename_axis("severity").reset_index(name="count")
        st.bar_chart(severity_counts.set_index("severity"))
        st.dataframe(dataframe, width="stretch")
    else:
        st.success("Tidak ada alert aktif saat ini.")


st.title("Alerts")
auto_refresh, interval_seconds = refresh_controls("alerts", default_enabled=True, default_interval=15)
st.caption(live_status_text(auto_refresh, interval_seconds))
render_live_section(auto_refresh, interval_seconds, _render_alerts_body)
