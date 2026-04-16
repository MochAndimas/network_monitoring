import streamlit as st
import pandas as pd
from urllib.parse import urlencode

from components.auth import is_admin, require_dashboard_login
from components.api import get_json, get_json_map, paged_items, paged_meta, post_json, put_json
from components.sidebar import collapse_sidebar_on_page_load

st.set_page_config(page_title="Devices", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()

st.title("Devices")
payload = get_json_map(
    {
        "devices": ("/devices?limit=1000&offset=0", []),
        "device_types": ("/devices/meta/types", []),
    }
)
devices = payload["devices"]
device_types = payload["device_types"]

type_labels = {item["label"]: item["value"] for item in device_types}

inventory_tab, manage_tab = st.tabs(["Inventory", "Manage"])

with inventory_tab:
    inventory_col1, inventory_col2, inventory_col3, inventory_col4 = st.columns(4)
    inventory_active_only = inventory_col1.checkbox("Active only", value=False)
    inventory_type_options = ["All"] + [item["value"] for item in device_types]
    selected_inventory_type = inventory_col2.selectbox(
        "Filter device type",
        options=inventory_type_options,
        index=0,
        format_func=lambda value: "All" if value == "All" else value.replace("_", " ").title(),
    )
    inventory_status = inventory_col3.selectbox(
        "Latest status",
        options=["All", "unknown", "up", "ok", "warning", "down", "error"],
        index=0,
    )
    inventory_search = inventory_col4.text_input("Search", placeholder="Nama, IP, atau site")

    paging_col1, paging_col2 = st.columns([1, 3])
    inventory_page_size = paging_col1.selectbox("Rows per page", options=[25, 50, 100, 200], index=1)
    inventory_page_number = paging_col2.number_input("Page", min_value=1, value=1, step=1)

    inventory_query_params = {
        "limit": inventory_page_size,
        "offset": (int(inventory_page_number) - 1) * inventory_page_size,
    }
    if inventory_active_only:
        inventory_query_params["active_only"] = "true"
    if selected_inventory_type != "All":
        inventory_query_params["device_type"] = selected_inventory_type
    if inventory_status != "All":
        inventory_query_params["latest_status"] = inventory_status
    if inventory_search.strip():
        inventory_query_params["search"] = inventory_search.strip()

    inventory_query = urlencode(inventory_query_params)
    inventory_payload = get_json(f"/devices/paged?{inventory_query}", {"items": [], "meta": {}})
    inventory_devices = paged_items(inventory_payload)
    inventory_meta = paged_meta(inventory_payload)

    if inventory_devices:
        dataframe = pd.DataFrame(inventory_devices)
        left, center, right = st.columns(3)
        left.metric("Rows Loaded", int(len(dataframe)))
        center.metric("Total Match", int(inventory_meta.get("total", len(dataframe))))
        right.metric("Devices Down", int((dataframe["latest_status"] == "down").sum()))
        st.caption(
            f"Menampilkan {inventory_meta.get('offset', 0) + 1}-"
            f"{inventory_meta.get('offset', 0) + len(dataframe)} dari {inventory_meta.get('total', len(dataframe))} device."
        )
        st.dataframe(dataframe, use_container_width=True)
    else:
        st.info("Tidak ada device yang cocok dengan filter inventory saat ini.")

with manage_tab:
    if not is_admin():
        st.info("Halaman manage device hanya tersedia untuk role admin.")
    elif not device_types:
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
                edit_key_prefix = f"edit_device_{selected_device['id']}"

                existing_type_label = next(
                    (label for label, value in type_labels.items() if value == selected_device["device_type"]),
                    list(type_labels.keys())[0],
                )

                with st.form("edit_device_form"):
                    edit_name = st.text_input("Name", value=selected_device["name"], key=f"{edit_key_prefix}_name")
                    edit_ip = st.text_input("IP Address", value=selected_device["ip_address"], key=f"{edit_key_prefix}_ip")
                    edit_type_label = st.selectbox(
                        "Device Type",
                        options=list(type_labels.keys()),
                        index=list(type_labels.keys()).index(existing_type_label),
                        key=f"{edit_key_prefix}_type",
                    )
                    edit_site = st.text_input("Site", value=selected_device.get("site") or "", key=f"{edit_key_prefix}_site")
                    edit_description = st.text_area(
                        "Description",
                        value=selected_device.get("description") or "",
                        key=f"{edit_key_prefix}_description",
                    )
                    edit_active = st.checkbox("Active", value=selected_device["is_active"], key=f"{edit_key_prefix}_active")
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
