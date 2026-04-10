import streamlit as st
import pandas as pd

from components.api import get_json, post_json, put_json
from components.sidebar import collapse_sidebar_on_page_load

st.set_page_config(page_title="Devices", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()

st.title("Devices")
devices = get_json("/devices", [])
device_types = get_json("/devices/meta/types", [])

type_labels = {item["label"]: item["value"] for item in device_types}

inventory_tab, manage_tab = st.tabs(["Inventory", "Manage"])

with inventory_tab:
    if devices:
        dataframe = pd.DataFrame(devices)
        left, right = st.columns(2)
        left.metric("Total Devices", int(len(dataframe)))
        right.metric("Devices Down", int((dataframe["latest_status"] == "down").sum()))

        filter_types = ["All"] + sorted(dataframe["device_type"].dropna().unique().tolist())
        selected_type = st.selectbox("Filter device type", options=filter_types, index=0)
        if selected_type != "All":
            dataframe = dataframe[dataframe["device_type"] == selected_type]

        st.dataframe(dataframe, use_container_width=True)
    else:
        st.info("Belum ada device yang tersedia. Jalankan seed device atau aktifkan monitor terlebih dahulu.")

with manage_tab:
    if not device_types:
        st.warning("Daftar device type belum tersedia dari backend.")
    else:
        create_column, edit_column = st.columns(2)

        with create_column:
            st.subheader("Add Device")
            with st.form("create_device_form", clear_on_submit=True):
                create_name = st.text_input("Name", placeholder="Google DNS")
                create_ip = st.text_input("IP Address", placeholder="8.8.8.8")
                create_type_label = st.selectbox("Device Type", options=list(type_labels.keys()), key="create_device_type")
                create_site = st.text_input("Site", placeholder="WAN")
                create_description = st.text_area("Description", placeholder="Target monitoring ISP utama")
                create_active = st.checkbox("Active", value=True)
                create_submitted = st.form_submit_button("Create Device", use_container_width=True)

            if create_submitted:
                payload = {
                    "name": create_name.strip(),
                    "ip_address": create_ip.strip(),
                    "device_type": type_labels[create_type_label],
                    "site": create_site.strip() or None,
                    "description": create_description.strip() or None,
                    "is_active": create_active,
                }
                result = post_json("/devices", payload, None)
                if result:
                    st.success(f"Device `{result['name']}` berhasil ditambahkan.")
                    st.rerun()

        with edit_column:
            st.subheader("Edit Device")
            if not devices:
                st.info("Belum ada device untuk diedit.")
            else:
                device_lookup = {
                    f"{device['name']} ({device['ip_address']})": device
                    for device in devices
                }
                selected_device_label = st.selectbox("Select Device", options=list(device_lookup.keys()))
                selected_device = device_lookup[selected_device_label]

                existing_type_label = next(
                    (label for label, value in type_labels.items() if value == selected_device["device_type"]),
                    list(type_labels.keys())[0],
                )

                with st.form("edit_device_form"):
                    edit_name = st.text_input("Name", value=selected_device["name"], key="edit_name")
                    edit_ip = st.text_input("IP Address", value=selected_device["ip_address"], key="edit_ip")
                    edit_type_label = st.selectbox(
                        "Device Type",
                        options=list(type_labels.keys()),
                        index=list(type_labels.keys()).index(existing_type_label),
                        key="edit_device_type",
                    )
                    edit_site = st.text_input("Site", value=selected_device.get("site") or "", key="edit_site")
                    edit_description = st.text_area(
                        "Description",
                        value=selected_device.get("description") or "",
                        key="edit_description",
                    )
                    edit_active = st.checkbox("Active", value=selected_device["is_active"], key="edit_active")
                    update_submitted = st.form_submit_button("Update Device", use_container_width=True)

                if update_submitted:
                    payload = {
                        "name": edit_name.strip(),
                        "ip_address": edit_ip.strip(),
                        "device_type": type_labels[edit_type_label],
                        "site": edit_site.strip() or None,
                        "description": edit_description.strip() or None,
                        "is_active": edit_active,
                    }
                    result = put_json(f"/devices/{selected_device['id']}", payload, None)
                    if result:
                        st.success(f"Device `{result['name']}` berhasil diperbarui.")
                        st.rerun()
