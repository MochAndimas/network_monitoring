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
            "`PRINTER_SNMP_COMMUNITIES` berisi IP printer, SNMP v1/v2c aktif, UDP 161 terbuka, "
            "lalu jalankan monitoring cycle."
        )
        return

    latest_map = _latest_metric_snapshot_map(printer_history_frame)
    collection_row = latest_map.get("printer_snmp_collection_status")
    status_row = latest_map.get("printer_status")
    error_row = latest_map.get("printer_error_state")
    ink_status_row = latest_map.get("printer_ink_status")
    toner_black_row = latest_map.get("printer_toner_black_percent")
    paper_row = latest_map.get("printer_paper_status")
    paper_detail_row = latest_map.get("printer_paper_detail")
    uptime_row = latest_map.get("printer_uptime_seconds")
    pages_row = latest_map.get("printer_total_pages")
    st.markdown("### Kesehatan Printer")
    st.caption("Ringkasan status printer, deteksi gangguan, uptime, dan counter halaman.")
    if collection_row is not None and str(collection_row["display_value"]).lower() != "ok":
        protocol = str(collection_row.get("unit") or "SNMP").upper()
        st.warning(
            f"Data SNMP belum dapat dikumpulkan ({collection_row['display_value']}, {protocol}). "
            "Status kertas, toner, dan counter di bawah mungkin bukan kondisi printer terbaru. "
            "Cek VPN/ACL UDP 161, community read-only, dan versi SNMP."
        )
    status_cards = [
        (
            "Kolektor SNMP",
            str(collection_row["display_value"]) if collection_row is not None else "Belum ada data",
            f"Protokol: {str(collection_row.get('unit') or '-').upper()}" if collection_row is not None else "",
        ),
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
            (
                f"Lokasi: {str(paper_detail_row['display_value'])}"
                if paper_detail_row is not None
                else (f"Status metrik: {str(paper_row['status']).upper()}" if paper_row is not None else "")
            ),
        ),
        (
            "Status Tinta",
            str(ink_status_row["display_value"]) if ink_status_row is not None else "-",
            "Status consumable keseluruhan dari printer",
        ),
        (
            "Toner Black",
            str(toner_black_row["display_value"]) if toner_black_row is not None else "-",
            "Level toner hitam dari SNMP Printer MIB",
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
    for cards_in_row in (status_cards[:4], status_cards[4:]):
        columns = st.columns(len(cards_in_row))
        for column, (label, value, meta) in zip(columns, cards_in_row, strict=False):
            with column.container(border=True):
                st.metric(label, value)
                if meta:
                    st.caption(meta)



__all__ = ["_render_printer_history_section"]
