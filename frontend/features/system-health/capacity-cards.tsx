import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import type { SystemHealthSummary } from "./types";

const read = (source: Record<string, unknown>, key: string) => String(source[key] ?? "-");

export function CapacityCards({ summary }: { summary: SystemHealthSummary }) {
  const cards = [
    ["DB pool", read(summary.database_pool, "checked_out")],
    ["DB overflow", read(summary.database_pool, "overflow")],
    ["Job lagging", read(summary.scheduler_queue, "lagging_jobs")],
    ["Misfire", read(summary.scheduler_queue, "misfire_count")],
    ["Metric write/min", read(summary.raw_metric_write_rate, "last_minute")]
  ];
  return <section><h2>Kapasitas dan Antrian</h2><MetricGrid columns={5}>{cards.map(([label, value]) => <MetricCard key={label} label={label} value={value} />)}</MetricGrid></section>;
}
