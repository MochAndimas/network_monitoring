"use client";

import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/components/ui/data-table";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PageHeader } from "@/components/ui/page-header";
import { MetaStrip } from "@/components/ui/meta-strip";
import { CsvExport } from "@/components/ui/csv-export";
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
    <MetaStrip items={[{ label: "Refresh otomatis", value: "Aktif (15 dtk)" }, { label: "Database", value: summary.database }, { label: "Operational alert", value: summary.operational_alerts.length }, { label: "Terakhir dirender", value: formatWib(new Date().toISOString()) }]} />

    <MetricGrid columns={5}>
      <MetricCard label="Database" value={summary.database} />
      <MetricCard label="Device" value={summary.devices_total.toLocaleString("id-ID")} />
      <MetricCard label="Latest metric" value={summary.metrics_latest_snapshot.toLocaleString("id-ID")} />
      <MetricCard label="Alert aktif" value={summary.alerts_active.toLocaleString("id-ID")} />
      <MetricCard label="Insiden aktif" value={summary.incidents_active.toLocaleString("id-ID")} />
    </MetricGrid>

    <CapacityCards summary={summary} />

    <section>
      <div className="section-header"><h2>Operational Alerts</h2><CsvExport filename="system-health-operational-alerts.csv" columns={["Job", "Severity", "Penyebab", "Detail"]} rows={summary.operational_alerts.map((item) => [value(item, "job_name"), value(item, "severity"), value(item, "reason"), value(item, "message")])} /></div>
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
      <div className="section-header"><h2>Scheduler Jobs</h2><CsvExport filename="system-health-scheduler-jobs.csv" columns={["Job", "Running", "Failure beruntun", "Durasi terakhir", "Sukses terakhir"]} rows={summary.scheduler_jobs.map((item) => [item.job_name, item.is_running ? "Ya" : "Tidak", item.consecutive_failures, item.last_duration_ms, formatWib(item.last_succeeded_at)])} /></div>
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
      <div className="section-header"><h2>Scheduler Timing</h2><CsvExport filename="system-health-scheduler-timing.csv" columns={["Job", "Status", "Schedule lag", "Heartbeat"]} rows={summary.scheduler_health.map((item) => [value(item, "job_name"), value(item, "state"), value(item, "schedule_lag_seconds"), value(item, "last_heartbeat_at")])} /></div>
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
      <div className="section-header"><h2>Kesehatan Collector</h2><CsvExport filename="system-health-collectors.csv" columns={["Collector", "Status", "Success rate", "Timeout", "Tindakan"]} rows={summary.collector_health.map((item) => [value(item, "collector"), value(item, "state"), value(item, "success_rate_percent"), value(item, "timeout_count"), value(item, "action")])} /></div>
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
      <div className="section-header"><h2>Performa Collector 24 Jam</h2><CsvExport filename="system-health-collector-runs.csv" columns={["Collector", "Run", "Berhasil", "Rata-rata durasi", "Terakhir"]} rows={summary.collector_runs.map((item) => [value(item, "collector"), value(item, "runs"), value(item, "successful_runs"), value(item, "average_duration_ms"), value(item, "last_checked_at")])} /></div>
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
