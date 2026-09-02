"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { formatWib, statusLabel } from "@/lib/formatters";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { MetaStrip } from "@/components/ui/meta-strip";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { StatusBadge } from "@/components/ui/status-badge";
import { DataTable } from "@/components/ui/data-table";
import { CsvExport } from "@/components/ui/csv-export";
import { PageHeader } from "@/components/ui/page-header";
import { PermissionGate } from "@/components/ui/permission-gate";
import { FreshnessLabel } from "@/components/ui/freshness-label";
import { PlotlyChart, statusChartColor } from "@/components/charts/plotly-chart";
import type { OverviewData } from "./types";

export function OverviewPage() {
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => apiFetch<OverviewData>("/dashboard/overview-data"), refetchInterval: 15_000 });
  if (overview.isPending) return <LoadingState />;
  if (overview.isError) return <ErrorState message="Overview tidak dapat dimuat." onRetry={() => void overview.refetch()} />;
  const data = overview.data;
  const statuses = data.device_counts.statuses ?? {};
  const problemRows = data.problem_devices.filter((device) => ["down", "warning", "error"].includes(device.latest_status));

  return <main className="app-page">
    <PageHeader title="Overview" description="Ringkasan kesehatan jaringan dan antrian gangguan aktif." actions={<PermissionGate fallback={<span>Mode baca saja</span>}><RunCycleButton /></PermissionGate>} />
    <MetaStrip items={[{ label: "Refresh Otomatis", value: "Aktif (15 dtk)" }, { label: "Terakhir Diperbarui", value: formatWib(new Date().toISOString()) }, { label: "Pemeriksaan Terakhir (WIB)", value: formatWib(data.device_counts.latest_check_at) }]} />
    <h2>Status Global</h2><MetricGrid>{[
      ["Internet", statusLabel(data.summary.internet_status)], ["Mikrotik", statusLabel(data.summary.mikrotik_status)],
      ["Server", statusLabel(data.summary.server_status)], ["Alert Aktif", data.summary.active_alerts]
    ].map(([label, value]) => <MetricCard key={label} label={String(label)} value={String(value)} />)}</MetricGrid>
    <h2>Snapshot Operasional</h2><MetricGrid columns={5}>{[
      ["Total Device", data.device_counts.total], ["Device Aktif", data.device_counts.active], ["Device Down", statuses.down ?? 0],
      ["Device Warning", statuses.warning ?? 0], ["Insiden Aktif", data.incidents.length]
    ].map(([label, value]) => <MetricCard key={label} label={String(label)} value={String(value)} />)}</MetricGrid>
    <section className="two-column"><section><div className="section-header"><h2>Device Perlu Perhatian</h2><CsvExport filename="device-perlu-perhatian.csv" columns={["Device", "IP", "Tipe", "Site", "Status", "Freshness", "Dicek WIB"]} rows={problemRows.map((item) => [item.name, item.ip_address, item.device_type, item.site, item.latest_status, item.latest_checked_at, formatWib(item.latest_checked_at)])} /></div><DataTable columns={[{ key: "name", label: "Device", render: (item) => item.name }, { key: "ip", label: "IP Address", render: (item) => item.ip_address }, { key: "type", label: "Type", render: (item) => item.device_type }, { key: "site", label: "Site", render: (item) => item.site ?? "-" }, { key: "status", label: "Status", render: (item) => <StatusBadge value={item.latest_status} /> }, { key: "freshness", label: "Freshness", render: (item) => <FreshnessLabel checkedAt={item.latest_checked_at} /> }, { key: "checked", label: "Pemeriksaan Terakhir (WIB)", render: (item) => formatWib(item.latest_checked_at) }]} rows={problemRows} /></section>
      <section><div className="section-header"><h2>Distribusi Tingkat Alert</h2></div><PlotlyChart ariaLabel="Distribusi tingkat alert aktif" data={[{ type: "bar", orientation: "h", x: Object.values(data.alert_severity_summary), y: Object.keys(data.alert_severity_summary), marker: { color: Object.keys(data.alert_severity_summary).map(statusChartColor) }, hovertemplate: "%{y}: %{x}<extra></extra>" }]} layout={{ xaxis: { title: { text: "Jumlah alert" } }, yaxis: { automargin: true, autorange: "reversed" } }} /><DataTable columns={[{ key: "severity", label: "Tingkat", render: ([severity]) => <StatusBadge value={severity} /> }, { key: "count", label: "Jumlah", render: ([, count]) => count }]} rows={Object.entries(data.alert_severity_summary)} /></section></section>
    <section className="two-column"><section><h2>Alert Aktif Terbaru</h2><DataTable columns={[{ key: "created", label: "Dibuat (WIB)", render: (item) => formatWib(item.created_at) }, { key: "device", label: "Device", render: (item) => item.device_name }, { key: "severity", label: "Tingkat", render: (item) => <StatusBadge value={item.severity} /> }, { key: "message", label: "Pesan", render: (item) => item.message }]} rows={data.alerts} /></section>
      <section><h2>Insiden Aktif</h2><DataTable columns={[{ key: "started", label: "Mulai (WIB)", render: (item) => formatWib(item.started_at) }, { key: "device", label: "Device", render: (item) => item.device_name }, { key: "summary", label: "Ringkasan", render: (item) => item.summary }, { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> }]} rows={data.incidents} /></section></section>
    <section><div className="section-header"><h2>Snapshot Metric Terbaru</h2><CsvExport filename="snapshot-metric-terbaru.csv" columns={["Dicek WIB", "Device", "Metrik", "Nilai", "Status", "Freshness"]} rows={data.latest_snapshot.items.map((item) => [formatWib(item.checked_at), item.device_name, item.metric_name, `${item.metric_value}${item.unit ? ` ${item.unit}` : ""}`, item.status, item.checked_at])} /></div><DataTable columns={[{ key: "checked", label: "Dicek (WIB)", render: (item) => formatWib(item.checked_at) }, { key: "device", label: "Device", render: (item) => item.device_name }, { key: "metric", label: "Metrik", render: (item) => item.metric_name }, { key: "value", label: "Nilai", render: (item) => `${item.metric_value}${item.unit ? ` ${item.unit}` : ""}` }, { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> }, { key: "freshness", label: "Freshness", render: (item) => <FreshnessLabel checkedAt={item.checked_at} /> }]} rows={data.latest_snapshot.items} /></section>
  </main>;
}

function RunCycleButton() {
  const [pending, setPending] = useState(false);
  async function run() { setPending(true); try { await apiFetch("/system/run-cycle", { method: "POST" }); } finally { setPending(false); } }
  return <button type="button" disabled={pending} onClick={() => void run()}>{pending ? "Menjalankan…" : "Jalankan Monitoring Cycle"}</button>;
}
