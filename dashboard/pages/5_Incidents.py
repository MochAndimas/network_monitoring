import pandas as pd
import streamlit as st

from components.auth import require_dashboard_login
from components.api import get_json
from components.refresh import live_status_text, refresh_controls, render_live_section, rendered_at_label
from components.sidebar import collapse_sidebar_on_page_load
from components.time_utils import format_wib_timestamp, to_wib_timestamp

st.set_page_config(page_title="Incidents", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()


st.title("Incidents")
status_filter = st.selectbox("Filter incident status", options=["All", "active", "resolved"], index=0)
auto_refresh, interval_seconds = refresh_controls("incidents", default_enabled=True, default_interval=15)
st.caption(live_status_text(auto_refresh, interval_seconds))


def _render_incidents_body() -> None:
    path = "/incidents"
    if status_filter != "All":
        path = f"/incidents?status={status_filter}"

    incidents = get_json(path, [])
    st.caption(f"Render terakhir: {rendered_at_label()}")

    if incidents:
        dataframe = pd.DataFrame(incidents)
        if "started_at" in dataframe.columns:
            dataframe["started_at"] = to_wib_timestamp(dataframe["started_at"])
            dataframe["started_at"] = dataframe["started_at"].apply(format_wib_timestamp)
        if "ended_at" in dataframe.columns:
            dataframe["ended_at"] = to_wib_timestamp(dataframe["ended_at"])
            dataframe["ended_at"] = dataframe["ended_at"].apply(format_wib_timestamp)
        left, right = st.columns(2)
        left.metric("Total Incidents", int(len(dataframe)))
        right.metric("Active Incidents", int((dataframe["status"] == "active").sum()))
        st.dataframe(dataframe, width="stretch")
    else:
        st.info("Belum ada incident yang tercatat.")


render_live_section(auto_refresh, interval_seconds, _render_incidents_body)
