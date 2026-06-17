"""Printer-specific live monitoring helpers."""

import pandas as pd
import streamlit as st

from .device_common import _latest_metric_snapshot_map

def _render_printer_history_section(
    printer_history_frame: pd.DataFrame,
) -> None:
    """Render printer-specific status and consumable history views."""
    if printer_history_frame.empty:
        st.info(
            "Belum ada metrik printer SNMP. Pastikan device bertipe `printer`, "
            "`PRINTER_SNMP_COMMUNITIES` berisi IP printer, SNMP v2c aktif, UDP 161 terbuka, "
            "lalu jalankan monitoring cycle."
        )
        return

    latest_map = _latest_metric_snapshot_map(printer_history_frame)
    status_row = latest_map.get("printer_status")
    error_row = latest_map.get("printer_error_state")
    ink_status_row = latest_map.get("printer_ink_status")
    paper_row = latest_map.get("printer_paper_status")
    uptime_row = latest_map.get("printer_uptime_seconds")
    pages_row = latest_map.get("printer_total_pages")
    st.markdown("### Kesehatan Printer")
    st.caption("Ringkasan status printer, deteksi gangguan, uptime, dan counter halaman.")
    status_columns = st.columns(6)
    status_cards = [
        (
            "Status Keseluruhan",
            str(status_row["display_value"]) if status_row is not None else "-",
            f"Status metrik: {str(status_row['status']).upper()}" if status_row is not None else "",
        ),
        (
            "Status Error",
            str(error_row["display_value"]) if error_row is not None else "-",
            f"Tingkat: {str(error_row['status']).upper()}" if error_row is not None else "",
        ),
        (
            "Status Kertas",
            str(paper_row["display_value"]) if paper_row is not None else "-",
            f"Status metrik: {str(paper_row['status']).upper()}" if paper_row is not None else "",
        ),
        (
            "Status Tinta",
            str(ink_status_row["display_value"]) if ink_status_row is not None else "-",
            "Status consumable keseluruhan dari printer",
        ),
        (
            "Uptime",
            str(uptime_row["display_value"]) if uptime_row is not None else "-",
            "Dipakai untuk deteksi reboot",
        ),
        (
            "Total Halaman",
            str(pages_row["display_value"]) if pages_row is not None else "-",
            "Counter akumulatif printer",
        ),
    ]
    for column, (label, value, meta) in zip(status_columns, status_cards, strict=False):
        with column.container(border=True):
            st.metric(label, value)
            if meta:
                st.caption(meta)



__all__ = ["_render_printer_history_section"]
