"""Constants used by the live monitoring dashboard."""

STATUS_OPTIONS = ["All", "up", "down", "ok", "error", "warning", "unknown"]
CHART_WINDOW_OPTIONS = {
    "1 jam": 1,
    "6 jam": 6,
    "12 jam": 12,
    "24 jam": 24,
    "7 hari": 24 * 7,
}
METRIC_LABELS = {
    "ping": ("Ping Latency", "Waktu respon ping ke device/target."),
    "ping_collection_status": ("Status Kolektor ICMP", "Hasil collector ping dari server monitoring; bukan status target device."),
    "packet_loss": ("Packet Loss", "Persentase paket ping yang gagal sampai ke target."),
    "jitter": ("Jitter", "Rata-rata perubahan latency antar sample ping."),
    "dns_resolution_time": ("DNS Resolution", "Waktu yang dibutuhkan untuk resolve hostname DNS check."),
    "http_response_time": ("HTTP Response", "Waktu respon HTTP check ke URL yang dikonfigurasi."),
    "public_ip": ("Public IP", "IP public yang terlihat dari jaringan saat monitoring berjalan."),
    "reachability": ("Ping Latency", "Nama lama untuk metric ping latency."),
    "cpu_percent": ("CPU Usage", "Persentase penggunaan CPU."),
    "memory_percent": ("Memory Usage", "Persentase penggunaan RAM/memori."),
    "disk_percent": ("Disk Usage", "Persentase penggunaan disk."),
    "memory_used_bytes": ("Memory Used", "Memori terpakai dari Mikrotik."),
    "memory_free_bytes": ("Memory Free", "Memori kosong dari Mikrotik."),
    "disk_used_bytes": ("Storage Used", "Storage terpakai dari Mikrotik."),
    "disk_free_bytes": ("Storage Free", "Storage kosong dari Mikrotik."),
    "boot_time_epoch": ("Boot Time", "Waktu boot terakhir dalam epoch timestamp."),
    "interfaces_running": ("Active Interfaces", "Jumlah interface Mikrotik yang sedang running."),
    "dhcp_active_leases": ("DHCP Active Leases", "Jumlah lease DHCP aktif/bound di Mikrotik."),
    "connected_clients": ("Connected Clients", "Jumlah client unik dari DHCP lease aktif dan ARP table."),
    "mikrotik_api": ("Mikrotik API Status", "Status koneksi ke API Mikrotik."),
    "printer_uptime_seconds": ("Printer Uptime", "Durasi hidup printer sejak reboot terakhir."),
    "printer_status": ("Printer Status", "Status umum printer dari SNMP Host Resources MIB."),
    "printer_snmp_collection_status": ("Status Kolektor SNMP", "Hasil koneksi collector SNMP; bukan status hardware printer."),
    "printer_error_state": ("Status Error Printer", "Bitmask error printer yang sudah diterjemahkan ke label operasional."),
    "printer_ink_status": ("Ink Status", "Status tinta overall yang diturunkan dari status/error printer."),
    "printer_toner_black_percent": ("Toner Black", "Persentase toner hitam yang tersedia dari Printer MIB."),
    "printer_paper_status": ("Paper Status", "Kondisi kertas/tray printer berdasarkan SNMP."),
    "printer_paper_detail": ("Detail Tray Kertas", "Nama tray serta jumlah kertas yang dilaporkan printer."),
    "printer_total_pages": ("Total Pages", "Counter total halaman yang sudah tercetak."),
    "nas_uptime_seconds": ("NAS Uptime", "Durasi hidup NAS sejak reboot terakhir."),
    "nas_snmp_collection_status": ("Status Kolektor NAS SNMP", "Hasil koneksi collector NAS SNMP; bukan status hardware NAS."),
    "nas_system_status": ("NAS System Status", "Status sistem Synology dari SNMP."),
    "nas_power_status": ("NAS Power Status", "Status power supply Synology dari SNMP."),
    "nas_system_temperature_c": ("NAS System Temperature", "Suhu sistem NAS dari SNMP."),
}
PRINTER_METRIC_NAMES = [
    "printer_uptime_seconds",
    "printer_status",
    "printer_snmp_collection_status",
    "printer_error_state",
    "printer_ink_status",
    "printer_toner_black_percent",
    "printer_paper_status",
    "printer_paper_detail",
    "printer_total_pages",
]
INTERNET_ONLY_METRICS = {"dns_resolution_time", "http_response_time", "public_ip"}
PRINTER_DETAIL_ONLY_METRICS = {"printer_uptime_seconds", "printer_total_pages"}
NAS_CARD_ONLY_METRIC_NAMES = {
    "nas_uptime_seconds",
    "nas_system_status",
    "nas_power_status",
    "nas_system_temperature_c",
}
NAS_CARD_ONLY_DYNAMIC_PREFIXES = (
    "nas_fan:",
    "nas_volume:",
    "nas_raid:",
)
NAS_CARD_ONLY_DYNAMIC_STATUS_SUFFIXES = (":status",)

__all__ = [
    "CHART_WINDOW_OPTIONS",
    "INTERNET_ONLY_METRICS",
    "METRIC_LABELS",
    "NAS_CARD_ONLY_DYNAMIC_PREFIXES",
    "NAS_CARD_ONLY_DYNAMIC_STATUS_SUFFIXES",
    "NAS_CARD_ONLY_METRIC_NAMES",
    "PRINTER_DETAIL_ONLY_METRICS",
    "PRINTER_METRIC_NAMES",
    "STATUS_OPTIONS",
]
