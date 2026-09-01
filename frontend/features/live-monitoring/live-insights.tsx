import { PlotlyChart, statusChartColor } from "@/components/charts/plotly-chart";
import { DataTable } from "@/components/ui/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import type { MetricSample } from "./types";

function countBy(items: readonly MetricSample[], field: "device_name" | "metric_name" | "status") {
  return [...items.reduce((counts, item) => {
    const key = String(item[field] ?? "unknown");
    counts.set(key, (counts.get(key) ?? 0) + 1);
    return counts;
  }, new Map<string, number>())].sort(([, left], [, right]) => right - left);
}

export function LiveInsights({ samples, statusSummary }: { samples: MetricSample[]; statusSummary: Record<string, number> }) {
  const statuses = Object.entries(statusSummary);
  const activeDevices = countBy(samples, "device_name").slice(0, 6);
  const frequentMetrics = countBy(samples, "metric_name").slice(0, 6);

  return <section>
    <h2>Insight Analisis</h2>
    <div className="two-column">
      <section>
        <PlotlyChart
          ariaLabel="Distribusi status snapshot"
          data={[{ type: "pie", labels: statuses.map(([status]) => status), values: statuses.map(([, total]) => total), marker: { colors: statuses.map(([status]) => statusChartColor(status)) }, textinfo: "label+value" }]}
          layout={{ title: { text: "Distribusi Status" }, showlegend: true }}
        />
        <DataTable columns={[{ key: "status", label: "Status", render: ([status]) => <StatusBadge value={status} /> }, { key: "total", label: "Jumlah", render: ([, total]) => total }]} rows={statuses} />
      </section>
      <section>
        <h3>Device Paling Aktif</h3>
        <DataTable columns={[{ key: "device", label: "Device", render: ([device]) => device }, { key: "total", label: "Jumlah", render: ([, total]) => total }]} rows={activeDevices} />
        <h3>Metrik Paling Sering Muncul</h3>
        <DataTable columns={[{ key: "metric", label: "Metrik", render: ([metric]) => metric }, { key: "total", label: "Jumlah", render: ([, total]) => total }]} rows={frequentMetrics} />
      </section>
    </div>
  </section>;
}
