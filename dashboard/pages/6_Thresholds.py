import pandas as pd
import streamlit as st

from components.auth import is_admin, require_dashboard_login
from components.api import get_json, has_pending_action, put_json
from components.sidebar import collapse_sidebar_on_page_load

st.set_page_config(page_title="Thresholds", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()

st.title("Thresholds")
thresholds = get_json("/thresholds", [])

if thresholds:
    dataframe = pd.DataFrame(thresholds)
    st.dataframe(dataframe, use_container_width=True)

    key_options = dataframe["key"].tolist()
    selected_key = st.selectbox("Threshold key", options=key_options, index=0)
    current_value = float(dataframe.loc[dataframe["key"] == selected_key, "value"].iloc[0])
    updated_value = st.number_input("New value", value=current_value, step=1.0)

    if not is_admin():
        st.info("Role viewer hanya bisa melihat threshold.")
    else:
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
