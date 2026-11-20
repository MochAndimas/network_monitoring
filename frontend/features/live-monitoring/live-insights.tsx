import { PlotlyChart, statusChartColor } from "@/components/charts/plotly-chart";
import { DataTable } from "@/components/ui/data-table";

import { LiveActiveAlertSummary } from "@/features/alerts/active-alert-summary";
import type { MetricSample } from "./types";

function countBy(items: readonly MetricSample[], field: "device_name" | "metric_name" | "status") {
  return [...items.reduce((counts, item) => {
    const key = String(item[field] ?? "unknown");
    counts.set(key, (counts.get(key) ?? 0) + 1);
    return counts;
  }, new Map<string, number>())].sort(([, left], [, right]) => right - left);
}

export function LiveInsights({ samples, statusSummary, showActiveAlerts }: { samples: MetricSample[]; statusSummary: Record<string, number>; showActiveAlerts: boolean }) {
  const statuses = summarizeMetricHealth(statusSummary);
  const activeDevices = countBy(samples, "device_name").slice(0, 6);
  const frequentMetrics = countBy(samples, "metric_name").slice(0, 6);

  return <section>
    <h2>Insight Analisis</h2>
    {showActiveAlerts ? <LiveActiveAlertSummary /> : null}
    <div className="two-column">
      <section className="insight-distribution">
        <h3>Kondisi Metrik Perangkat</h3>
        <p className="section-caption">Perlu perhatian berarti ada metrik bermasalah, bukan berarti perangkat mati. Lihat detail metrik untuk penyebabnya.</p>
        <PlotlyChart
          ariaLabel="Distribusi status perangkat berdasarkan snapshot metrik"
          data={[{ type: "pie", labels: statuses.map(([status]) => status), values: statuses.map(([, total]) => total), marker: { colors: statuses.map(([status]) => statusChartColor(status === "Perlu perhatian" ? "warning" : status === "Normal" ? "ok" : "unknown")) }, textinfo: "none", hovertemplate: "%{label}: %{value}<extra></extra>" }]}
          layout={{ showlegend: true, margin: { l: 24, r: 24, t: 24, b: 24 } }}
        />
        <DataTable columns={[{ key: "status", label: "Kondisi metrik", render: ([status]) => <span className={`status-badge status-${status === "Perlu perhatian" ? "warning" : status === "Normal" ? "success" : "muted"}`}>{status}</span> }, { key: "total", label: "Jumlah perangkat", render: ([, total]) => total }]} rows={statuses} pageSize={null} />
      </section>
      <section className="insight-stack">
        <h3>Device Paling Aktif</h3>
        <DataTable columns={[{ key: "device", label: "Device", render: ([device]) => device }, { key: "total", label: "Jumlah", render: ([, total]) => total }]} rows={activeDevices} />
        <h3>Metrik Paling Sering Muncul</h3>
        <DataTable columns={[{ key: "metric", label: "Metrik", render: ([metric]) => metric }, { key: "total", label: "Jumlah", render: ([, total]) => total }]} rows={frequentMetrics} />
      </section>
    </div>
  </section>;
}

/** Aggregate metric severity must not be presented as proof of device availability. */
export function summarizeMetricHealth(summary: Record<string, number>): [string, number][] {
  const counts = new Map<string, number>();
  for (const [status, total] of Object.entries(summary)) {
    const normalized = status.toLowerCase();
    const label = ["down", "critical", "error", "warning"].includes(normalized)
      ? "Perlu perhatian" : ["up", "ok"].includes(normalized) ? "Normal" : "Belum diketahui";
    counts.set(label, (counts.get(label) ?? 0) + total);
  }
  return [...counts.entries()];
}
