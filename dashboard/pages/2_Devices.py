import streamlit as st
import pandas as pd
from urllib.parse import urlencode

from components.auth import is_admin, require_dashboard_login
from components.api import delete_json, get_json, get_json_map, has_pending_action, paged_items, paged_meta, post_json, put_json
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
type_label_by_value = {value: label for label, value in type_labels.items()}


def _clear_cached_gets() -> None:
    st.cache_data.clear()


def _device_type_label(device_type: str) -> str:
    return type_label_by_value.get(device_type, device_type.replace("_", " ").title())


@st.dialog("Edit Device")
def _render_edit_device_dialog(device: dict) -> None:
    edit_key_prefix = f"edit_device_{device['id']}"
    type_options = list(type_labels.keys())
    existing_type_label = _device_type_label(str(device.get("device_type") or ""))
    if existing_type_label not in type_options and type_options:
        existing_type_label = type_options[0]

    with st.form(f"{edit_key_prefix}_form"):
        edit_name = st.text_input("Name", value=device["name"], key=f"{edit_key_prefix}_name")
        edit_ip = st.text_input("IP Address", value=device["ip_address"], key=f"{edit_key_prefix}_ip")
        edit_type_label = st.selectbox(
            "Device Type",
            options=type_options,
            index=type_options.index(existing_type_label) if existing_type_label in type_options else 0,
            key=f"{edit_key_prefix}_type",
        )
        edit_site = st.text_input("Site", value=device.get("site") or "", key=f"{edit_key_prefix}_site")
        edit_description = st.text_area(
            "Description",
            value=device.get("description") or "",
            key=f"{edit_key_prefix}_description",
        )
        edit_active = st.checkbox("Active", value=bool(device["is_active"]), key=f"{edit_key_prefix}_active")
        submitted = st.form_submit_button("Update Device", use_container_width=True)

    if submitted:
        update_payload = {
            "name": edit_name.strip(),
            "ip_address": edit_ip.strip(),
            "device_type": type_labels[edit_type_label],
            "site": edit_site.strip() or None,
            "description": edit_description.strip() or None,
            "is_active": edit_active,
        }
        result = put_json(f"/devices/{device['id']}", update_payload, None, action_key=f"edit_device_{device['id']}")
        if result:
            _clear_cached_gets()
            st.success(f"Device `{result['name']}` berhasil diperbarui.")
            st.rerun()


@st.dialog("Delete Device")
def _render_delete_device_dialog(device: dict) -> None:
    st.warning(f"Hapus device `{device['name']}` ({device['ip_address']})?")
    st.caption("Metric device ini akan ikut dihapus. Alert dan incident lama tetap disimpan tanpa relasi device.")
    confirm = st.text_input("Ketik DELETE untuk konfirmasi", key=f"delete_device_{device['id']}_confirm")
    left, right = st.columns(2)
    if left.button("Delete Device", type="primary", use_container_width=True, disabled=confirm != "DELETE"):
        result = delete_json(f"/devices/{device['id']}", False, action_key=f"delete_device_{device['id']}")
        if result:
            _clear_cached_gets()
            st.success(f"Device `{device['name']}` berhasil dihapus.")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


def _render_manage_device_table(rows: list[dict]) -> None:
    header = st.columns([1.4, 1.2, 1.2, 1.4, 0.8, 0.9, 0.9])
    for column, label in zip(header, ["Name", "IP", "Type", "Site", "Active", "Edit", "Delete"]):
        column.caption(label)

    for device in rows:
        columns = st.columns([1.4, 1.2, 1.2, 1.4, 0.8, 0.9, 0.9])
        columns[0].write(device["name"])
        columns[1].write(device["ip_address"])
        columns[2].write(device["device_type"])
        columns[3].write(device.get("site") or "-")
        columns[4].write("Active" if device.get("is_active") else "Inactive")
        if columns[5].button("Edit", key=f"open_edit_device_{device['id']}", use_container_width=True):
            _render_edit_device_dialog(device)
        if columns[6].button("Delete", key=f"open_delete_device_{device['id']}", use_container_width=True):
            _render_delete_device_dialog(device)

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
        create_column, list_column = st.columns([1, 2])

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
                result = post_json("/devices", payload, None, action_key="create_device")
                if result:
                    _clear_cached_gets()
                    st.success(f"Device `{result['name']}` berhasil ditambahkan.")
                    st.rerun()
            elif has_pending_action("create_device"):
                result = post_json("/devices", None, None, action_key="create_device")
                if result:
                    _clear_cached_gets()
                    st.success(f"Device `{result['name']}` berhasil ditambahkan.")
                    st.rerun()

        with list_column:
            st.subheader("Manage Existing Devices")
            if not devices:
                st.info("Belum ada device untuk dikelola.")
            else:
                manage_search = st.text_input("Search device", placeholder="Nama, IP, atau site")
                search_text = manage_search.strip().lower()
                filtered_devices = [
                    device
                    for device in devices
                    if not search_text
                    or search_text in str(device.get("name") or "").lower()
                    or search_text in str(device.get("ip_address") or "").lower()
                    or search_text in str(device.get("site") or "").lower()
                ]
                _render_manage_device_table(filtered_devices)
