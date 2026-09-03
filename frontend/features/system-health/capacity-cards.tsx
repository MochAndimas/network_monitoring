import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import type { SystemHealthSummary } from "./types";

const read = (source: Record<string, unknown>, key: string) => String(source[key] ?? "-");

export function CapacityCards({ summary }: { summary: SystemHealthSummary }) {
  const cards = [
    ["DB Pool Dipakai", `${read(summary.database_pool, "checked_out")} / ${read(summary.database_pool, "capacity")}`],
    ["DB Pool Overflow", read(summary.database_pool, "overflow")],
    ["Job Tertinggal", read(summary.scheduler_queue, "lagging_jobs")],
    ["Misfire Tercatat", read(summary.scheduler_queue, "misfire_count")],
    ["Lock Contention", read(summary.pipeline_locks, "contention_count")],
    ["Metric / Menit", read(summary.raw_metric_write_rate, "per_minute_last_hour")],
    ["Metric 1 Menit", read(summary.raw_metric_write_rate, "last_minute")],
    ["Metric 1 Jam", read(summary.raw_metric_write_rate, "last_hour")]
  ];
  return <section>
    <h2>Kapasitas dan Antrian</h2>
    <p className="section-caption">Counter lock adalah observasi proses backend ini; scheduler memakai advisory lock MySQL terpisah.</p>
    <MetricGrid columns={4}>{cards.map(([label, value]) => <MetricCard key={label} label={label} value={value} />)}</MetricGrid>
  </section>;
}
