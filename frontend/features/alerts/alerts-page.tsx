"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch, withQuery } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { PageHeader } from "@/components/ui/page-header";
import { MetaStrip } from "@/components/ui/meta-strip";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { CsvExport } from "@/components/ui/csv-export";
import { StatusBadge } from "@/components/ui/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PlotlyChart, statusChartColor } from "@/components/charts/plotly-chart";
import { initialOffset, useUrlQuerySync } from "@/lib/use-url-query-sync";

type Alert = { id: number; device_name: string | null; site: string | null; alert_type: string; severity: string; message: string; status: string; created_at: string; resolved_at: string | null };
type AlertPage = { items: Alert[]; meta: { total: number; limit: number; offset: number } };
const LIMIT = 50;

export function AlertsPage() {
  const params = useSearchParams(); const [severity, setSeverity] = useState(() => params.get("severity") ?? ""); const [site, setSite] = useState(() => params.get("site") ?? ""); const [alertType, setAlertType] = useState(() => params.get("type") ?? ""); const [deviceId, setDeviceId] = useState(() => params.get("device") ?? ""); const [search, setSearch] = useState(() => params.get("q") ?? ""); const [sort, setSort] = useState<"newest" | "severity">(() => params.get("sort") === "severity" ? "severity" : "newest"); const [offset, setOffset] = useState(() => initialOffset(params.get("offset")));
  useUrlQuerySync({ severity, site, type: alertType, device: deviceId, q: search, sort: sort === "newest" ? undefined : sort, offset });
  const alerts = useQuery({ queryKey: ["alerts", severity, site, alertType, deviceId, search, sort, offset], queryFn: () => apiFetch<AlertPage>(withQuery("/alerts/active/paged", { severity, site, alert_type: alertType, device_id: deviceId ? Number(deviceId) : undefined, search, sort, limit: LIMIT, offset })), refetchInterval: 15_000 });
  if (alerts.isPending) return <LoadingState />; if (alerts.isError) return <ErrorState message="Alert aktif tidak dapat dimuat." onRetry={() => void alerts.refetch()} />;
  const data = alerts.data; const items = data.items; const criticalHigh = items.filter((item) => ["critical", "high"].includes(item.severity.toLowerCase())).length; const affectedDevices = new Set(items.map((item) => item.device_name).filter(Boolean)).size;
  const severityCounts = Object.entries(items.reduce<Record<string, number>>((result, item) => ({ ...result, [item.severity]: (result[item.severity] ?? 0) + 1 }), {}));
  const deviceCounts = Object.entries(items.reduce<Record<string, number>>((result, item) => ({ ...result, [item.device_name ?? "Unknown"]: (result[item.device_name ?? "Unknown"] ?? 0) + 1 }), {})).sort((left, right) => right[1] - left[1]).slice(0, 6);
  const reset = () => setOffset(0);
  return <main className="app-page"><PageHeader title="Alerts" description="Alert aktif, cakupan gangguan, dan prioritas respons operasional." />
    <MetaStrip items={[{ label: "Refresh otomatis", value: "Aktif (15 dtk)" }, { label: "Filter", value: [severity, site, alertType, deviceId, search].filter(Boolean).join(" · ") || "Semua alert aktif" }, { label: "Terakhir dirender", value: formatWib(new Date().toISOString()) }]} />
    <MetricGrid>{[["Total Alert Aktif", data.meta.total], ["Critical / High", criticalHigh], ["Device Terdampak", affectedDevices], ["Alert Tertua", data.items.length ? formatWib(data.items[data.items.length - 1].created_at) : "-"]].map(([label, value]) => <MetricCard key={String(label)} label={String(label)} value={String(value)} />)}</MetricGrid>
    <div className="filter-panel"><label>Severity<select value={severity} onChange={(event) => { setSeverity(event.target.value); reset(); }}><option value="">Semua severity</option>{["critical", "high", "warning", "low"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>Site<input value={site} placeholder="Semua site" onChange={(event) => { setSite(event.target.value); reset(); }} /></label><label>Tipe alert<input value={alertType} placeholder="Contoh: ping_down" onChange={(event) => { setAlertType(event.target.value); reset(); }} /></label><label>Device ID<input type="number" min="1" value={deviceId} onChange={(event) => { setDeviceId(event.target.value); reset(); }} /></label><label>Cari<input value={search} placeholder="Device atau pesan" onChange={(event) => { setSearch(event.target.value); reset(); }} /></label><label>Urutkan<select value={sort} onChange={(event) => { setSort(event.target.value as "newest" | "severity"); reset(); }}><option value="newest">Terbaru</option><option value="severity">Severity tertinggi</option></select></label></div>
    <section className="two-column"><section><h2>Distribusi Tingkat Alert</h2><PlotlyChart ariaLabel="Distribusi severity alert" data={[{ type: "bar", x: severityCounts.map(([label]) => label), y: severityCounts.map(([, count]) => count), marker: { color: severityCounts.map(([label]) => statusChartColor(label)) }, hovertemplate: "%{x}: %{y}<extra></extra>" }]} layout={{ yaxis: { title: { text: "Jumlah" } } }} /></section><section><h2>Device Paling Terdampak</h2><PlotlyChart ariaLabel="Device paling terdampak alert" data={[{ type: "bar", orientation: "h", x: deviceCounts.map(([, count]) => count), y: deviceCounts.map(([label]) => label), marker: { color: "#a8d8ff" }, hovertemplate: "%{y}: %{x}<extra></extra>" }]} layout={{ xaxis: { title: { text: "Jumlah alert" } }, yaxis: { autorange: "reversed" } }} /></section></section>
    <div className="section-header"><h2>Detail Alert Aktif</h2><CsvExport filename="alerts-aktif.csv" columns={["Dibuat WIB", "Resolved WIB", "Device", "Site", "Tipe", "Severity", "Status", "Pesan"]} rows={items.map((item) => [formatWib(item.created_at), formatWib(item.resolved_at), item.device_name, item.site, item.alert_type, item.severity, item.status, item.message])} /></div>
    <DataTable columns={[{ key: "created", label: "Dibuat (WIB)", render: (item) => formatWib(item.created_at) }, { key: "device", label: "Device", render: (item) => item.device_name ?? "-" }, { key: "site", label: "Site", render: (item) => item.site ?? "-" }, { key: "type", label: "Tipe", render: (item) => item.alert_type }, { key: "severity", label: "Severity", render: (item) => <StatusBadge value={item.severity} /> }, { key: "status", label: "Status", render: (item) => <StatusBadge value={item.status} /> }, { key: "message", label: "Pesan", render: (item) => item.message }, { key: "resolved", label: "Resolved (WIB)", render: (item) => formatWib(item.resolved_at) }]} rows={items} />
    <Pagination offset={offset} limit={LIMIT} total={data.meta.total} onChange={setOffset} />
  </main>;
}
