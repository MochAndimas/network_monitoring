"use client";

import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/components/ui/data-table";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PageHeader } from "@/components/ui/page-header";
import { apiFetch } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { CapacityCards } from "./capacity-cards";
import type { SchedulerJob, SystemHealthSummary, UnknownRecord } from "./types";

const value = (record: UnknownRecord, key: string) => String(record[key] ?? "-");
const number = (record: UnknownRecord, key: string) => Number(record[key] ?? 0).toLocaleString("id-ID");

function KeyValueTable({ rows }: { rows: UnknownRecord }) {
  const entries = Object.entries(rows).map(([key, item]) => ({ key, value: typeof item === "object" ? JSON.stringify(item) : String(item ?? "-") }));
  return <DataTable columns={[{ key: "key", label: "Key", render: (item) => item.key }, { key: "value", label: "Nilai", render: (item) => item.value }]} rows={entries} />;
}

export function SystemHealthPage() {
  const health = useQuery({
    queryKey: ["observability", "summary"],
    queryFn: () => apiFetch<SystemHealthSummary>("/observability/summary"),
    refetchInterval: 15_000
  });

  if (health.isPending) return <LoadingState />;
  if (health.isError) return <ErrorState message="System health tidak dapat dimuat." onRetry={() => void health.refetch()} />;

  const summary = health.data;
  return <main className="app-page">
    <PageHeader title="System Health" description="Kesehatan backend, scheduler, collector, dan pipeline monitoring. Diperbarui setiap 15 detik." />

    <MetricGrid columns={5}>
      <MetricCard label="Database" value={summary.database} />
      <MetricCard label="Device" value={summary.devices_total.toLocaleString("id-ID")} />
      <MetricCard label="Latest metric" value={summary.metrics_latest_snapshot.toLocaleString("id-ID")} />
      <MetricCard label="Alert aktif" value={summary.alerts_active.toLocaleString("id-ID")} />
      <MetricCard label="Insiden aktif" value={summary.incidents_active.toLocaleString("id-ID")} />
    </MetricGrid>

    <CapacityCards summary={summary} />

    <section>
      <h2>Operational Alerts</h2>
      <DataTable
        emptyLabel="Tidak ada operational alert aktif."
        columns={[
          { key: "job", label: "Job", render: (item) => value(item, "job_name") },
          { key: "severity", label: "Severity", render: (item) => value(item, "severity") },
          { key: "reason", label: "Penyebab", render: (item) => value(item, "reason") },
          { key: "message", label: "Detail", render: (item) => value(item, "message") }
        ]}
        rows={summary.operational_alerts}
      />
    </section>

    <section>
      <h2>Scheduler Jobs</h2>
      <DataTable<SchedulerJob>
        columns={[
          { key: "name", label: "Job", render: (item) => item.job_name },
          { key: "running", label: "Running", render: (item) => item.is_running ? "Ya" : "Tidak" },
          { key: "failures", label: "Failure beruntun", render: (item) => item.consecutive_failures },
          { key: "duration", label: "Durasi terakhir", render: (item) => item.last_duration_ms == null ? "-" : `${item.last_duration_ms} ms` },
          { key: "lastSuccess", label: "Sukses terakhir", render: (item) => formatWib(item.last_succeeded_at) }
        ]}
        rows={summary.scheduler_jobs}
      />
    </section>

    <section>
      <h2>Scheduler Timing</h2>
      <DataTable
        columns={[
          { key: "job", label: "Job", render: (item) => value(item, "job_name") },
          { key: "state", label: "Status", render: (item) => value(item, "state") },
          { key: "lag", label: "Schedule lag", render: (item) => `${number(item, "schedule_lag_seconds")} dtk` },
          { key: "heartbeat", label: "Heartbeat", render: (item) => formatWib(value(item, "last_heartbeat_at") === "-" ? null : value(item, "last_heartbeat_at")) }
        ]}
        rows={summary.scheduler_health}
      />
    </section>

    <section>
      <h2>Kesehatan Collector</h2>
      <DataTable
        columns={[
          { key: "collector", label: "Collector", render: (item) => value(item, "collector") },
          { key: "status", label: "Status", render: (item) => value(item, "state") },
          { key: "success", label: "Success rate", render: (item) => `${number(item, "success_rate_percent")}%` },
          { key: "timeout", label: "Timeout", render: (item) => number(item, "timeout_count") },
          { key: "action", label: "Tindakan", render: (item) => value(item, "action") }
        ]}
        rows={summary.collector_health}
      />
    </section>

    <section>
      <h2>Performa Collector 24 Jam</h2>
      <DataTable
        columns={[
          { key: "collector", label: "Collector", render: (item) => value(item, "collector") },
          { key: "runs", label: "Run", render: (item) => number(item, "runs") },
          { key: "success", label: "Berhasil", render: (item) => number(item, "successful_runs") },
          { key: "duration", label: "Rata-rata durasi", render: (item) => `${number(item, "average_duration_ms")} ms` },
          { key: "last", label: "Terakhir", render: (item) => formatWib(value(item, "last_checked_at") === "-" ? null : value(item, "last_checked_at")) }
        ]}
        rows={summary.collector_runs}
      />
    </section>

    <section>
      <h2>Auth Observability</h2>
      <KeyValueTable rows={summary.auth} />
    </section>
    <section>
      <h2>Runtime</h2>
      <KeyValueTable rows={summary.runtime} />
    </section>
  </main>;
}
