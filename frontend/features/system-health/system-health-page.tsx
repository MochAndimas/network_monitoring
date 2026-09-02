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
import type { FreshnessSummary, SchedulerJob, SystemHealthSummary, UnknownRecord } from "./types";

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
  const freshness = useQuery({ queryKey: ["metrics", "freshness", "summary"], queryFn: () => apiFetch<FreshnessSummary>("/metrics/freshness/summary?active_only=true"), refetchInterval: 15_000 });

  if (health.isPending || freshness.isPending) return <LoadingState />;
  if (health.isError || freshness.isError) return <ErrorState message="System health tidak dapat dimuat." onRetry={() => { void health.refetch(); void freshness.refetch(); }} />;

  const summary = health.data;
  const runningJobs = summary.scheduler_health.filter((item) => value(item, "state") === "running").length;
  const failingJobs = summary.scheduler_health.filter((item) => value(item, "state") === "failing").length;
  const staleJobs = summary.scheduler_health.filter((item) => value(item, "state") === "stale").length;
  const maxLagSeconds = Math.max(0, ...summary.scheduler_health.map((item) => Number(item.schedule_lag_seconds ?? 0)));
  return <main className="app-page">
    <PageHeader title="System Health" description="Kesehatan backend, scheduler, collector, dan pipeline monitoring. Diperbarui setiap 15 detik." />
    <MetaStrip items={[{ label: "Refresh otomatis", value: "Aktif (15 dtk)" }, { label: "Database", value: summary.database }, { label: "Operational alert", value: summary.operational_alerts.length }, { label: "Terakhir dirender", value: formatWib(new Date().toISOString()) }]} />

    <MetricGrid columns={8}>
      <MetricCard label="Database" value={summary.database} />
      <MetricCard label="Device" value={summary.devices_total.toLocaleString("id-ID")} />
      <MetricCard label="Latest metric" value={summary.metrics_latest_snapshot.toLocaleString("id-ID")} />
      <MetricCard label="Alert aktif" value={summary.alerts_active.toLocaleString("id-ID")} />
      <MetricCard label="Insiden aktif" value={summary.incidents_active.toLocaleString("id-ID")} />
      <MetricCard label="Job running" value={runningJobs.toLocaleString("id-ID")} />
      <MetricCard label="Job failing" value={failingJobs.toLocaleString("id-ID")} />
      <MetricCard label="Job stale" value={staleJobs.toLocaleString("id-ID")} />
      <MetricCard label="Lag terbesar" value={`${maxLagSeconds.toLocaleString("id-ID", { maximumFractionDigits: 0 })} dtk`} />
    </MetricGrid>

    <CapacityCards summary={summary} />

    <section>
      <div className="section-header"><h2>Operational Alerts</h2><CsvExport filename="system-health-operational-alerts.csv" columns={["Job", "Severity", "Penyebab", "Detail", "Error terakhir"]} rows={summary.operational_alerts.map((item) => [value(item, "job_name"), value(item, "severity"), value(item, "reason"), value(item, "message"), value(item, "last_error")])} /></div>
      <DataTable
        emptyLabel="Tidak ada operational alert aktif."
        columns={[
          { key: "job", label: "Job", render: (item) => value(item, "job_name") },
          { key: "severity", label: "Severity", render: (item) => value(item, "severity") },
          { key: "reason", label: "Penyebab", render: (item) => value(item, "reason") },
          { key: "message", label: "Detail", render: (item) => value(item, "message") },
          { key: "error", label: "Error terakhir", render: (item) => value(item, "last_error") }
        ]}
        rows={summary.operational_alerts}
      />
    </section>

    <section>
      <div className="section-header"><h2>Scheduler Jobs</h2><CsvExport filename="system-health-scheduler-jobs.csv" columns={["Job", "Running", "Failure beruntun", "Mulai terakhir", "Sukses terakhir", "Gagal terakhir", "Durasi terakhir"]} rows={summary.scheduler_jobs.map((item) => [item.job_name, item.is_running ? "Ya" : "Tidak", item.consecutive_failures, formatWib(item.last_started_at), formatWib(item.last_succeeded_at), formatWib(item.last_failed_at), item.last_duration_ms])} /></div>
      <DataTable<SchedulerJob>
        columns={[
          { key: "name", label: "Job", render: (item) => item.job_name },
          { key: "running", label: "Running", render: (item) => item.is_running ? "Ya" : "Tidak" },
          { key: "failures", label: "Failure beruntun", render: (item) => item.consecutive_failures },
          { key: "lastStarted", label: "Mulai terakhir", render: (item) => formatWib(item.last_started_at) },
          { key: "duration", label: "Durasi terakhir", render: (item) => item.last_duration_ms == null ? "-" : `${item.last_duration_ms} ms` },
          { key: "lastSuccess", label: "Sukses terakhir", render: (item) => formatWib(item.last_succeeded_at) },
          { key: "lastFailure", label: "Gagal terakhir", render: (item) => formatWib(item.last_failed_at) }
        ]}
        rows={summary.scheduler_jobs}
      />
    </section>

    <section>
      <div className="section-header"><h2>Scheduler Timing</h2><CsvExport filename="system-health-scheduler-timing.csv" columns={["Job", "Status", "Interval", "Umur heartbeat", "Schedule lag", "Batas stale", "Heartbeat terakhir", "Durasi terakhir"]} rows={summary.scheduler_health.map((item) => [value(item, "job_name"), value(item, "state"), value(item, "expected_interval_seconds"), value(item, "heartbeat_age_seconds"), value(item, "schedule_lag_seconds"), value(item, "stale_after_seconds"), formatWib(value(item, "last_heartbeat_at") === "-" ? null : value(item, "last_heartbeat_at")), value(item, "last_duration_ms")])} /></div>
      <DataTable
        columns={[
          { key: "job", label: "Job", render: (item) => value(item, "job_name") },
          { key: "state", label: "Status", render: (item) => value(item, "state") },
          { key: "interval", label: "Interval", render: (item) => `${number(item, "expected_interval_seconds")} dtk` },
          { key: "age", label: "Umur heartbeat", render: (item) => `${number(item, "heartbeat_age_seconds")} dtk` },
          { key: "lag", label: "Schedule lag", render: (item) => `${number(item, "schedule_lag_seconds")} dtk` },
          { key: "stale", label: "Batas stale", render: (item) => `${number(item, "stale_after_seconds")} dtk` },
          { key: "heartbeat", label: "Heartbeat", render: (item) => formatWib(value(item, "last_heartbeat_at") === "-" ? null : value(item, "last_heartbeat_at")) },
          { key: "duration", label: "Durasi", render: (item) => `${number(item, "last_duration_ms")} ms` }
        ]}
        rows={summary.scheduler_health}
      />
    </section>

    <section>
      <div className="section-header"><h2>Kesehatan Collector</h2><CsvExport filename="system-health-collectors.csv" columns={["Collector", "Site", "Tipe device", "Protocol", "Status", "Success rate", "Sampel", "Timeout", "OID tidak didukung", "Check terakhir", "Tindakan"]} rows={summary.collector_health.map((item) => [value(item, "collector"), value(item, "site"), value(item, "device_type"), value(item, "protocol"), value(item, "state"), value(item, "success_rate_percent"), value(item, "sample_count"), value(item, "timeout_count"), value(item, "unsupported_oid_count"), formatWib(value(item, "last_checked_at") === "-" ? null : value(item, "last_checked_at")), value(item, "action")])} /></div>
      <DataTable
        columns={[
          { key: "collector", label: "Collector", render: (item) => value(item, "collector") },
          { key: "site", label: "Site", render: (item) => value(item, "site") },
          { key: "type", label: "Tipe device", render: (item) => value(item, "device_type") },
          { key: "protocol", label: "Protocol", render: (item) => value(item, "protocol") },
          { key: "status", label: "Status", render: (item) => value(item, "state") },
          { key: "success", label: "Success rate", render: (item) => `${number(item, "success_rate_percent")}%` },
          { key: "samples", label: "Sampel", render: (item) => number(item, "sample_count") },
          { key: "timeout", label: "Timeout", render: (item) => number(item, "timeout_count") },
          { key: "unsupported", label: "OID tidak didukung", render: (item) => number(item, "unsupported_oid_count") },
          { key: "checked", label: "Check terakhir", render: (item) => formatWib(value(item, "last_checked_at") === "-" ? null : value(item, "last_checked_at")) },
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
      <div className="section-header"><div><h2>Freshness per Collector/Site</h2><p>Stale bila tidak ada metric baru dalam {freshness.data.stale_after_minutes} menit.</p></div><CsvExport filename="system-health-freshness.csv" columns={["Collector", "Site", "Freshness", "Total device", "Dengan data", "Fresh", "Stale", "Tanpa data", "Check terbaru WIB", "Check terlama WIB"]} rows={freshness.data.items.map((item) => [item.collector, item.site, item.freshness_status, item.total_devices, item.devices_with_data, item.fresh_devices, item.stale_devices, item.no_data_devices, formatWib(item.latest_checked_at), formatWib(item.oldest_checked_at)])} /></div>
      <DataTable columns={[{ key: "collector", label: "Collector", render: (item) => item.collector }, { key: "site", label: "Site", render: (item) => item.site }, { key: "status", label: "Freshness", render: (item) => item.freshness_status }, { key: "total", label: "Total device", render: (item) => item.total_devices }, { key: "data", label: "Dengan data", render: (item) => item.devices_with_data }, { key: "fresh", label: "Fresh", render: (item) => item.fresh_devices }, { key: "stale", label: "Stale", render: (item) => item.stale_devices }, { key: "none", label: "Tanpa data", render: (item) => item.no_data_devices }, { key: "latest", label: "Check terbaru (WIB)", render: (item) => formatWib(item.latest_checked_at) }]} rows={freshness.data.items} emptyLabel="Belum ada data freshness." />
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
