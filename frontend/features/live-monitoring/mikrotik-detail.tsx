import { PlotlyChart } from "@/components/charts/plotly-chart";
import { DataTable } from "@/components/ui/data-table";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { StatusBadge } from "@/components/ui/status-badge";
import type { MetricSample } from "./types";

type DynamicRow = { name: string; status: string | null; [key: string]: string | number | null };

function latestByMetric(samples: MetricSample[]) {
  return new Map(samples.slice().sort((left, right) => right.checked_at.localeCompare(left.checked_at)).map((item) => [item.metric_name, item]));
}

function bytes(value: number | null) {
  if (value === null) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = value;
  let unit = 0;
  while (Math.abs(amount) >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 }).format(amount)} ${units[unit]}`;
}

function percent(sample: MetricSample | undefined) {
  const value = sample?.metric_value_numeric;
  return value === null || value === undefined ? "-" : `${new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 }).format(value)}%`;
}

function dynamicRows(samples: MetricSample[], prefix: "interface" | "firewall") {
  const groups = new Map<string, DynamicRow>();
  latestByMetric(samples).forEach((sample, metricName) => {
    const parts = metricName.split(":");
    if (parts[0] !== prefix || (prefix === "interface" && parts.length !== 3) || (prefix === "firewall" && parts.length < 4)) return;
    const name = prefix === "interface" ? parts[1] : `${parts[1]} / ${parts[2].replaceAll("_", " ")}`;
    const metricKey = prefix === "interface" ? parts[2] : parts[3];
    const current = groups.get(name) ?? { name, status: "ok" };
    current[metricKey] = sample.metric_value_numeric;
    if (["warning", "down", "error"].includes(String(sample.status))) current.status = sample.status;
    groups.set(name, current);
  });
  return [...groups.values()];
}

export function MikrotikDetail({ samples }: { samples: MetricSample[] }) {
  const latest = latestByMetric(samples);
  const apiStatus = latest.get("mikrotik_api")?.metric_value ?? "-";
  const interfaces = dynamicRows(samples, "interface").filter((item) => ["rx_bytes", "tx_bytes", "rx_mbps", "tx_mbps"].some((key) => Number(item[key] ?? 0) > 0));
  const firewall = dynamicRows(samples, "firewall").sort((left, right) => Number(right.pps ?? 0) - Number(left.pps ?? 0) || Number(right.mbps ?? 0) - Number(left.mbps ?? 0) || Number(right.packets ?? 0) - Number(left.packets ?? 0)).slice(0, 12);

  return <section>
    <h2>Metrik MikroTik</h2>
    {apiStatus.toLowerCase() !== "ok" ? <p className="form-error">Collector RouterOS API bermasalah ({apiStatus}). Data CPU, client, interface, queue, dan firewall mungkin stale.</p> : null}
    <MetricGrid columns={6}>
      <MetricCard label="RouterOS API" value={apiStatus} />
      <MetricCard label="CPU Load" value={percent(latest.get("cpu_percent"))} />
      <MetricCard label="Memory Used" value={percent(latest.get("memory_percent"))} />
      <MetricCard label="Storage Used" value={percent(latest.get("disk_percent"))} />
      <MetricCard label="DHCP Leases" value={latest.get("dhcp_active_leases")?.metric_value ?? "-"} />
      <MetricCard label="Connected Clients" value={latest.get("connected_clients")?.metric_value ?? "-"} />
    </MetricGrid>

    <h2>Interface Traffic</h2>
    <div className="two-column">
      <PlotlyChart ariaLabel="Traffic interface MikroTik" data={[
        { type: "bar", orientation: "h", name: "RX Mbps", x: interfaces.map((item) => Number(item.rx_mbps ?? 0)), y: interfaces.map((item) => item.name) },
        { type: "bar", orientation: "h", name: "TX Mbps", x: interfaces.map((item) => Number(item.tx_mbps ?? 0)), y: interfaces.map((item) => item.name) }
      ]} layout={{ barmode: "group", xaxis: { title: { text: "Mbps" } }, yaxis: { title: { text: "Interface" }, categoryorder: "total ascending" }, showlegend: true }} />
      <DataTable
        emptyLabel="Belum ada data interface traffic."
        columns={[
          { key: "name", label: "Interface", render: (item) => item.name },
          { key: "rxBytes", label: "RX Bytes", render: (item) => bytes(Number(item.rx_bytes ?? 0)) },
          { key: "txBytes", label: "TX Bytes", render: (item) => bytes(Number(item.tx_bytes ?? 0)) },
          { key: "rx", label: "RX Mbps", render: (item) => Number(item.rx_mbps ?? 0).toFixed(2) },
          { key: "tx", label: "TX Mbps", render: (item) => Number(item.tx_mbps ?? 0).toFixed(2) },
          { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> }
        ]}
        rows={interfaces}
      />
    </div>

    <h2>Firewall / NAT Counters</h2>
    <DataTable
      emptyLabel="Belum ada counter firewall/NAT."
      columns={[
        { key: "rule", label: "Rule", render: (item) => item.name },
        { key: "packets", label: "Packets", render: (item) => Number(item.packets ?? 0).toLocaleString("id-ID") },
        { key: "bytes", label: "Bytes", render: (item) => bytes(Number(item.bytes ?? 0)) },
        { key: "pps", label: "PPS", render: (item) => Number(item.pps ?? 0).toFixed(1) },
        { key: "mbps", label: "Mbps", render: (item) => Number(item.mbps ?? 0).toFixed(2) },
        { key: "spike", label: "Spike", render: (item) => item.status === "warning" ? "Possible spike" : "-" }
      ]}
      rows={firewall}
    />
  </section>;
}
