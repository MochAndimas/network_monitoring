import { DataTable } from "@/components/ui/data-table";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatWib } from "@/lib/formatters";
import type { MetricSample } from "./types";

function latestByMetric(samples: MetricSample[]) {
  return new Map(samples.slice().sort((left, right) => right.checked_at.localeCompare(left.checked_at)).map((item) => [item.metric_name, item]));
}

function bytes(value: number | null | undefined) {
  if (value == null) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = value;
  let unit = 0;
  while (Math.abs(amount) >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 }).format(amount)} ${units[unit]}`;
}

function percent(sample: MetricSample | undefined) {
  return sample?.metric_value_numeric == null ? "-" : `${new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 }).format(sample.metric_value_numeric)}%`;
}

function duration(sample: MetricSample | undefined) {
  const seconds = sample?.metric_value_numeric;
  if (seconds == null) return "-";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  return `${days ? `${days}h ` : ""}${hours}j ${minutes}m`;
}

export function NasDetail({ samples }: { samples: MetricSample[] }) {
  const latest = latestByMetric(samples);
  const collector = latest.get("nas_snmp_collection_status");
  const volumes = new Map<string, Record<string, MetricSample>>();
  const hardware: MetricSample[] = [];
  const temperatures: MetricSample[] = [];

  latest.forEach((sample, name) => {
    const parts = name.split(":");
    if (parts[0] === "nas_volume" && parts.length === 3) volumes.set(parts[1], { ...(volumes.get(parts[1]) ?? {}), [parts[2]]: sample });
    if ((parts[0] === "nas_raid" || parts[0] === "nas_disk" || parts[0] === "nas_fan") && parts.at(-1) === "status") hardware.push(sample);
    if (parts[0] === "nas_disk" && parts.at(-1) === "temperature_c") temperatures.push(sample);
  });

  const volumeRows = [...volumes.entries()].map(([name, metrics]) => ({
    name: name.replaceAll("_", " "), status: metrics.status?.metric_value ?? "-", total: bytes(metrics.total_bytes?.metric_value_numeric), used: bytes(metrics.used_bytes?.metric_value_numeric), free: bytes(metrics.free_bytes?.metric_value_numeric), percent: percent(metrics.used_percent), checkedAt: metrics.status?.checked_at ?? metrics.used_percent?.checked_at ?? ""
  }));

  return <section>
    <h2>Kesehatan NAS</h2>
    {collector && collector.metric_value.toLowerCase() !== "ok" ? <p className="form-error">Data NAS SNMP belum dapat dikumpulkan ({collector.metric_value}). Status volume, RAID, disk, dan temperatur mungkin stale.</p> : null}
    <MetricGrid columns={4}>
      <MetricCard label="Kolektor SNMP" value={collector?.metric_value ?? "-"} />
      <MetricCard label="CPU" value={percent(latest.get("cpu_percent"))} />
      <MetricCard label="Memory" value={percent(latest.get("memory_percent"))} />
      <MetricCard label="Volume Used" value={percent(latest.get("disk_percent"))} />
    </MetricGrid>
    <MetricGrid columns={3}>
      <MetricCard label="System Temp" value={latest.get("nas_system_temperature_c")?.metric_value_numeric == null ? "-" : `${latest.get("nas_system_temperature_c")?.metric_value_numeric} °C`} />
      <MetricCard label="System" value={latest.get("nas_system_status")?.metric_value ?? "-"} />
      <MetricCard label="Uptime" value={duration(latest.get("nas_uptime_seconds"))} />
    </MetricGrid>

    <h2>Kapasitas Volume</h2>
    <DataTable emptyLabel="Belum ada detail kapasitas volume NAS." columns={[
      { key: "name", label: "Volume", render: (item) => item.name },
      { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> },
      { key: "total", label: "Total", render: (item) => item.total },
      { key: "used", label: "Terpakai", render: (item) => item.used },
      { key: "free", label: "Sisa", render: (item) => item.free },
      { key: "percent", label: "Used", render: (item) => item.percent },
      { key: "checked", label: "Dicek (WIB)", render: (item) => formatWib(item.checkedAt) }
    ]} rows={volumeRows} />

    <div className="two-column">
      <section><h2>Status Hardware</h2><DataTable emptyLabel="Belum ada status hardware NAS." columns={[
        { key: "component", label: "Komponen", render: (item) => item.metric_name.replace(/^nas_[^:]+:/, "").replaceAll(":", " ").replaceAll("_", " ") },
        { key: "value", label: "Nilai", render: (item) => item.metric_value },
        { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> },
        { key: "checked", label: "Dicek (WIB)", render: (item) => formatWib(item.checked_at) }
      ]} rows={hardware} /></section>
      <section><h2>Temperatur Disk</h2><DataTable emptyLabel="Belum ada temperatur disk NAS." columns={[
        { key: "disk", label: "Disk", render: (item) => item.metric_name.split(":")[1]?.replaceAll("_", " ") ?? "-" },
        { key: "temperature", label: "Temperature", render: (item) => `${item.metric_value_numeric ?? item.metric_value} °C` },
        { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> },
        { key: "checked", label: "Dicek (WIB)", render: (item) => formatWib(item.checked_at) }
      ]} rows={temperatures} /></section>
    </div>
  </section>;
}
