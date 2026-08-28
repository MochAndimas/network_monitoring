"""Live Monitoring Streamlit page controller."""

from datetime import datetime, timedelta

import streamlit as st

from shared.device_utils import format_device_label
try:
    from components.auth import require_dashboard_login
    from components.api import get_json
    from components.refresh import refresh_controls, render_live_section
    from components.sidebar import collapse_sidebar_on_page_load
    from components.ui import render_page_header
except ModuleNotFoundError:  # pragma: no cover - supports imports outside Streamlit's app root
    from dashboard.components.auth import require_dashboard_login
    from dashboard.components.api import get_json
    from dashboard.components.refresh import refresh_controls, render_live_section
    from dashboard.components.sidebar import collapse_sidebar_on_page_load
    from dashboard.components.ui import render_page_header

from dashboard.pages.live_monitoring.body import render_history_body
from dashboard.pages.live_monitoring.filters import render_history_filters


def render_live_monitoring_page() -> None:
    """Render the Live Monitoring dashboard page."""
    st.set_page_config(page_title="Live Monitoring", layout="wide", initial_sidebar_state="collapsed")
    collapse_sidebar_on_page_load()
    require_dashboard_login()

    render_page_header(
        "Live Monitoring",
        "Monitoring metrik live untuk analisis tren dan investigasi insiden.",
    )

    devices = get_json("/devices/options?active_only=false&limit=300&offset=0", [])
    device_type_by_id = {int(device["id"]): str(device.get("device_type") or "") for device in devices}
    device_name_by_id = {int(device["id"]): str(device.get("name") or "") for device in devices}
    device_by_id = {int(device["id"]): device for device in devices}
    voip_devices = [device for device in devices if str(device.get("device_type") or "") == "voip"]
    voip_group_label = f"Semua VoIP ({len(voip_devices)} device)"
    device_options: dict[str, int | None] = {"Semua Device": None}
    for device in devices:
        # VoIP is monitored as one operational group; individual selection
        # would only duplicate the group chart and make the filter unwieldy.
        if len(voip_devices) >= 2 and str(device.get("device_type") or "") == "voip":
            continue
        device_options[format_device_label(device)] = int(device["id"])
    if len(voip_devices) >= 2:
        # The special option has no device ID; filters carry its member IDs separately.
        device_options[voip_group_label] = None

    today = datetime.now().date()
    default_start_date = today - timedelta(days=1)
    auto_refresh, interval_seconds = refresh_controls("history", default_enabled=True, default_interval=15)
    history_filters = render_history_filters(
        devices=devices,
        device_options=device_options,
        device_by_id=device_by_id,
        voip_group_label=voip_group_label if len(voip_devices) >= 2 else None,
        voip_device_ids=[int(device["id"]) for device in voip_devices],
        today=today,
        default_start_date=default_start_date,
        auto_refresh=auto_refresh,
    )

    render_live_section(
        auto_refresh,
        interval_seconds,
        lambda: render_history_body(
            history_filters=history_filters,
            auto_refresh=auto_refresh,
            interval_seconds=interval_seconds,
            device_type_by_id=device_type_by_id,
            device_name_by_id=device_name_by_id,
        ),
    )
