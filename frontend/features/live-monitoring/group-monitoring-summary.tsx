import Link from "next/link";
import { DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatWib } from "@/lib/formatters";
import type { MetricGroupMeta } from "./types";

export function GroupMonitoringSummary({ group, label, onPageChange }: {
  group: MetricGroupMeta;
  label: string;
  onPageChange: (offset: number) => void;
}) {
  return <section>
    <h2>Perangkat dalam grup {label}</h2>
    <p>Halaman ini menampilkan {group.devices.length} dari {group.total_devices} perangkat. Ringkasan dan data di bawah mengikuti halaman ini.</p>
    <p>Tren menampilkan maksimal 8 metrik dan {group.samples_per_series} sampel terbaru per perangkat/metrik. {group.trend_sampled ? "Riwayat lebih panjang dibatasi; buka detail perangkat untuk investigasi." : ""} Pilih satu metrik untuk melihat seri tertentu. Nilai teks dibatasi {group.value_char_limit} karakter.</p>
    <p>Riwayat Detail memuat hingga 100 data terbaru sesuai filter. Buka detail perangkat untuk penelusuran lebih lanjut.</p>
    {group.metric_names_truncated ? <p>Daftar pilihan metrik dibatasi pada 64 nama.</p> : null}
    <DataTable rows={group.devices} pageSize={null} emptyLabel="Tidak ada perangkat aktif untuk grup ini." columns={[
      { key: "device", label: "Device", render: (item) => <Link href={`/live-monitoring?device=${item.id}`}>{item.name}</Link> },
      { key: "site", label: "Site", render: (item) => item.site ?? "-" },
      { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> },
      { key: "freshness", label: "Freshness", render: (item) => item.freshness === "no_data" ? "Belum ada data" : item.freshness === "stale" ? "Stale" : "Fresh" },
      { key: "time", label: "Dicek (WIB)", render: (item) => formatWib(item.latest_checked_at) }
    ]} />
    <Pagination offset={group.device_offset} limit={group.device_limit} total={group.total_devices} onChange={onPageChange} />
  </section>;
}
