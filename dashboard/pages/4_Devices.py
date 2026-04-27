"""Define module logic for `dashboard/pages/4_Devices.py`.

This module contains project-specific implementation details.
"""

from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from components.auth import is_admin, require_dashboard_login
from components.api import delete_json, get_json, get_json_map, has_pending_action, paged_items, paged_meta, post_json, put_json
from components.sidebar import collapse_sidebar_on_page_load
from components.ui import normalize_status_label, render_kpi_cards, render_page_header

st.set_page_config(page_title="Devices", layout="wide", initial_sidebar_state="collapsed")
collapse_sidebar_on_page_load()
require_dashboard_login()

render_page_header(
    "Devices",
    "Inventaris perangkat monitoring dan pengelolaan data master device.",
)
payload = get_json_map(
    {
        "devices": ("/devices/options?active_only=false&limit=300&offset=0", []),
        "device_types": ("/devices/meta/types", []),
    }
)
devices = payload["devices"]
device_types = payload["device_types"]

type_labels = {item["label"]: item["value"] for item in device_types}
type_label_by_value = {value: label for label, value in type_labels.items()}


def _clear_cached_gets() -> None:
    """Perform clear cached gets.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    st.cache_data.clear()


def _device_type_label(device_type: str) -> str:
    """Perform device type label.

    Args:
        device_type: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return type_label_by_value.get(device_type, device_type.replace("_", " ").title())


def _prepare_manage_frame(rows: list[dict]) -> pd.DataFrame:
    """Perform prepare manage frame.

    Args:
        rows: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        return dataframe
    dataframe["site"] = dataframe["site"].fillna("-")
    dataframe["active_label"] = dataframe["is_active"].map(lambda value: "Aktif" if bool(value) else "Nonaktif")
    dataframe["type_label"] = dataframe["device_type"].astype(str).map(_device_type_label)
    dataframe["selector_label"] = (
        dataframe["name"].astype(str)
        + " ("
        + dataframe["ip_address"].astype(str)
        + " | "
        + dataframe["type_label"].astype(str)
        + ")"
    )
    return dataframe


@st.dialog("Ubah Device")
def _render_edit_device_dialog(device: dict) -> None:
    """Render edit device dialog.

    Args:
        device: Parameter input untuk routine ini.

    """
    edit_key_prefix = f"edit_device_{device['id']}"
    type_options = list(type_labels.keys())
    existing_type_label = _device_type_label(str(device.get("device_type") or ""))
    if existing_type_label not in type_options and type_options:
        existing_type_label = type_options[0]

    with st.form(f"{edit_key_prefix}_form"):
        edit_name = st.text_input("Nama", value=device["name"], key=f"{edit_key_prefix}_name")
        edit_ip = st.text_input("IP Address", value=device["ip_address"], key=f"{edit_key_prefix}_ip")
        edit_type_label = st.selectbox(
            "Tipe Device",
            options=type_options,
            index=type_options.index(existing_type_label) if existing_type_label in type_options else 0,
            key=f"{edit_key_prefix}_type",
        )
        edit_site = st.text_input("Lokasi", value=device.get("site") or "", key=f"{edit_key_prefix}_site")
        edit_description = st.text_area(
            "Deskripsi",
            value=device.get("description") or "",
            key=f"{edit_key_prefix}_description",
        )
        edit_active = st.checkbox("Aktif", value=bool(device["is_active"]), key=f"{edit_key_prefix}_active")
        submitted = st.form_submit_button("Simpan Perubahan", width="stretch")

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


@st.dialog("Hapus Device")
def _render_delete_device_dialog(device: dict) -> None:
    """Render delete device dialog.

    Args:
        device: Parameter input untuk routine ini.

    """
    st.warning(f"Hapus device `{device['name']}` ({device['ip_address']})?")
    st.caption("Metric device ini akan ikut dihapus. Alert dan incident lama tetap disimpan tanpa relasi device.")
    confirm = st.text_input("Ketik DELETE untuk konfirmasi", key=f"delete_device_{device['id']}_confirm")
    left, right = st.columns(2)
    if left.button("Hapus Device", type="primary", width="stretch", disabled=confirm != "DELETE"):
        result = delete_json(f"/devices/{device['id']}", False, action_key=f"delete_device_{device['id']}")
        if result:
            _clear_cached_gets()
            st.success(f"Device `{device['name']}` berhasil dihapus.")
            st.rerun()
    if right.button("Batal", width="stretch"):
        st.rerun()


inventory_tab, manage_tab = st.tabs(["Inventory", "Kelola"])

with inventory_tab:
    inventory_col1, inventory_col2 = st.columns([2, 1])
    inventory_search = inventory_col1.text_input("Cari", placeholder="Nama, IP, atau site")
    inventory_status = inventory_col2.selectbox(
        "Status Terakhir",
        options=["All", "unknown", "up", "ok", "warning", "down", "error"],
        index=0,
        format_func=lambda value: "Semua" if value == "All" else normalize_status_label(str(value)),
    )
    with st.expander("Filter Lanjutan"):
        advanced_col1, advanced_col2, advanced_col3, advanced_col4 = st.columns(4)
        inventory_active_only = advanced_col1.checkbox("Hanya Aktif", value=False)
        inventory_type_options = ["All"] + [item["value"] for item in device_types]
        selected_inventory_type = advanced_col2.selectbox(
            "Tipe Device",
            options=inventory_type_options,
            index=0,
            format_func=lambda value: "Semua" if value == "All" else value.replace("_", " ").title(),
        )
        inventory_page_size = advanced_col3.selectbox("Baris per Halaman", options=[25, 50, 100, 200], index=1)
        inventory_page_number = advanced_col4.number_input("Halaman", min_value=1, value=1, step=1)

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
        dataframe["status_label"] = dataframe["latest_status"].map(normalize_status_label)
        dataframe["type_label"] = dataframe["device_type"].astype(str).map(_device_type_label)
        dataframe["active_label"] = dataframe["is_active"].map(lambda value: "Aktif" if bool(value) else "Nonaktif")

        render_kpi_cards(
            [
                ("Baris Tertampil", int(len(dataframe)), None),
                ("Total Cocok", int(inventory_meta.get("total", len(dataframe))), None),
                ("Device Down", int((dataframe["latest_status"] == "down").sum()), None),
                ("Device Warning", int((dataframe["latest_status"] == "warning").sum()), None),
            ],
            columns_per_row=4,
        )
        st.caption(
            f"Menampilkan {inventory_meta.get('offset', 0) + 1}-"
            f"{inventory_meta.get('offset', 0) + len(dataframe)} dari {inventory_meta.get('total', len(dataframe))} device."
        )
        inventory_view = dataframe[
            ["name", "ip_address", "type_label", "site", "status_label", "active_label"]
        ].rename(
            columns={
                "name": "Nama Device",
                "ip_address": "Alamat IP",
                "type_label": "Tipe",
                "site": "Lokasi",
                "status_label": "Status Terakhir",
                "active_label": "Status Aktif",
            }
        )
        st.dataframe(
            inventory_view,
            width="stretch",
            hide_index=True,
            column_config={
                "Nama Device": st.column_config.TextColumn("Nama Device", width="medium"),
                "Alamat IP": st.column_config.TextColumn("Alamat IP", width="small"),
                "Tipe": st.column_config.TextColumn("Tipe", width="small"),
                "Lokasi": st.column_config.TextColumn("Lokasi", width="small"),
                "Status Terakhir": st.column_config.TextColumn("Status Terakhir", width="small"),
                "Status Aktif": st.column_config.TextColumn("Status Aktif", width="small"),
            },
        )
    else:
        st.info("Tidak ada device yang cocok dengan filter. Ubah status, tipe, atau kata kunci pencarian.")

with manage_tab:
    if not is_admin():
        st.info("Mode kelola device hanya tersedia untuk role admin.")
    elif not device_types:
        st.warning("Daftar device type belum tersedia dari backend.")
    else:
        create_column, manage_column = st.columns([1, 2])

        with create_column:
            st.subheader("Tambah Device")
            with st.form("create_device_form", clear_on_submit=True):
                create_name = st.text_input("Nama", placeholder="Google DNS")
                create_ip = st.text_input("IP Address", placeholder="8.8.8.8")
                create_type_label = st.selectbox("Tipe Device", options=list(type_labels.keys()), key="create_device_type")
                create_site = st.text_input("Lokasi", placeholder="WAN")
                create_description = st.text_area("Deskripsi", placeholder="Target monitoring ISP utama")
                create_active = st.checkbox("Aktif", value=True)
                create_submitted = st.form_submit_button("Tambah Device", width="stretch")

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

        with manage_column:
            st.subheader("Kelola Device")
            if not devices:
                st.info("Belum ada device untuk dikelola. Tambahkan device baru di panel kiri.")
            else:
                manage_search = st.text_input("Cari", placeholder="Nama, IP, site")
                with st.expander("Filter Lanjutan"):
                    filter_col1, filter_col2 = st.columns([1, 1])
                    manage_type = filter_col1.selectbox(
                        "Tipe",
                        options=["All"] + [item["value"] for item in device_types],
                        format_func=lambda value: "Semua" if value == "All" else _device_type_label(str(value)),
                    )
                    manage_active = filter_col2.selectbox(
                        "Status Aktif",
                        options=["All", "Active", "Inactive"],
                        index=0,
                        format_func=lambda value: {
                            "All": "Semua",
                            "Active": "Aktif",
                            "Inactive": "Nonaktif",
                        }.get(value, value),
                    )

                manage_frame = _prepare_manage_frame(devices)
                if manage_search.strip():
                    needle = manage_search.strip().lower()
                    manage_frame = manage_frame[
                        manage_frame["name"].astype(str).str.lower().str.contains(needle, na=False)
                        | manage_frame["ip_address"].astype(str).str.lower().str.contains(needle, na=False)
                        | manage_frame["site"].astype(str).str.lower().str.contains(needle, na=False)
                    ]
                if manage_type != "All":
                    manage_frame = manage_frame[manage_frame["device_type"] == manage_type]
                if manage_active != "All":
                    expected = manage_active == "Active"
                    manage_frame = manage_frame[manage_frame["is_active"].astype(bool) == expected]

                render_kpi_cards(
                    [
                        ("Device Tersaring", int(len(manage_frame)), None),
                        ("Aktif", int(manage_frame["is_active"].astype(bool).sum()) if not manage_frame.empty else 0, None),
                        (
                            "Nonaktif",
                            int((~manage_frame["is_active"].astype(bool)).sum()) if not manage_frame.empty else 0,
                            None,
                        ),
                    ],
                    columns_per_row=3,
                )

                if manage_frame.empty:
                    st.info("Tidak ada device yang cocok dengan filter kelola. Ubah filter untuk menampilkan data.")
                else:
                    view_frame = manage_frame[
                        ["name", "ip_address", "type_label", "site", "active_label"]
                    ].rename(
                        columns={
                            "name": "Nama Device",
                            "ip_address": "Alamat IP",
                            "type_label": "Tipe",
                            "site": "Lokasi",
                            "active_label": "Status Aktif",
                        }
                    )
                    st.dataframe(
                        view_frame,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Nama Device": st.column_config.TextColumn("Nama Device", width="medium"),
                            "Alamat IP": st.column_config.TextColumn("Alamat IP", width="small"),
                            "Tipe": st.column_config.TextColumn("Tipe", width="small"),
                            "Lokasi": st.column_config.TextColumn("Lokasi", width="small"),
                            "Status Aktif": st.column_config.TextColumn("Status Aktif", width="small"),
                        },
                    )

                    selector_map = {
                        row["selector_label"]: row.to_dict()
                        for _, row in manage_frame.sort_values(["name", "ip_address"]).iterrows()
                    }
                    selected_label = st.selectbox(
                        "Device Terpilih",
                        options=list(selector_map.keys()),
                        index=0,
                    )
                    selected_device = selector_map[selected_label]

                    action_col1, action_col2 = st.columns([1, 1])
                    if action_col1.button("Ubah Device Terpilih", width="stretch"):
                        _render_edit_device_dialog(selected_device)
                    if action_col2.button("Hapus Device Terpilih", type="primary", width="stretch"):
                        _render_delete_device_dialog(selected_device)
