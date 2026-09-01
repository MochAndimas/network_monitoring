"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ChangeEvent } from "react";
import { apiFetch, withQuery } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { CsvExport } from "@/components/ui/csv-export";
import { PageHeader } from "@/components/ui/page-header";
import { MetaStrip } from "@/components/ui/meta-strip";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PlotlyChart } from "@/components/charts/plotly-chart";

type Rollup = { id: number; device_name: string; device_type: string | null; site: string | null; rollup_date: string; total_samples: number; ping_samples: number; down_count: number; uptime_percentage: number | null; average_ping_ms: number | null; min_ping_ms: number | null; max_ping_ms: number | null; average_packet_loss_percent: number | null; average_jitter_ms: number | null; max_jitter_ms: number | null; updated_at: string };
type Response = { items: Rollup[]; meta: { total: number; limit: number; offset: number } };
type DeviceTypeOption = { value: string; label: string };
const value = (item: number | null, suffix = "") => item === null ? "-" : `${item.toLocaleString("id-ID", { maximumFractionDigits: 2 })}${suffix}`;

export function DailySummaryPage() {
  const [site, setSite] = useState(""); const [deviceType, setDeviceType] = useState(""); const [from, setFrom] = useState(""); const [to, setTo] = useState(""); const [offset, setOffset] = useState(0); const limit = 50;
  const query = useQuery({ queryKey: ["daily-summary", site, deviceType, from, to, offset], queryFn: () => apiFetch<Response>(withQuery("/metrics/daily-summary", { site, device_type: deviceType, rollup_from: from, rollup_to: to, limit, offset })) });
  const types = useQuery({ queryKey: ["device-types"], queryFn: () => apiFetch<DeviceTypeOption[]>("/devices/meta/types"), staleTime: Infinity });
  if (query.isPending) return <LoadingState />; if (query.isError) return <ErrorState message="Daily summary tidak dapat dimuat." onRetry={() => void query.refetch()} />;
  const data = query.data;
  const reset = (setter: (value: string) => void) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setter(event.target.value); setOffset(0); };
  return <main className="app-page"><PageHeader title="Daily Summary" description="Rollup harian uptime dan kualitas koneksi dari backend." />
    <MetaStrip items={[{ label: "Sumber", value: "Daily rollup" }, { label: "Total", value: data.meta.total }, { label: "Terakhir dirender", value: formatWib(new Date().toISOString()) }]} />
    <div className="filter-panel"><label>Site<input value={site} onChange={reset(setSite)} placeholder="Semua site" /></label><label>Tipe device<select value={deviceType} onChange={reset(setDeviceType)}><option value="">Semua tipe</option>{types.data?.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Dari<input type="date" value={from} onChange={reset(setFrom)} /></label><label>Sampai<input type="date" value={to} onChange={reset(setTo)} /></label></div>
    <section className="two-column"><section><h2>Tren Uptime</h2><PlotlyChart ariaLabel="Tren uptime harian" data={[{ type: "scatter", mode: "lines+markers", x: data.items.map((item) => item.rollup_date), y: data.items.map((item) => item.uptime_percentage), name: "Uptime", line: { color: "#8df0c3" }, hovertemplate: "%{x}<br>%{y:.2f}%<extra></extra>" }]} layout={{ yaxis: { title: { text: "Uptime (%)" }, range: [0, 100] }, xaxis: { title: { text: "Tanggal" } } }} /></section><section><h2>Rata-rata Ping</h2><PlotlyChart ariaLabel="Tren rata-rata ping harian" data={[{ type: "scatter", mode: "lines+markers", x: data.items.map((item) => item.rollup_date), y: data.items.map((item) => item.average_ping_ms), name: "Ping", line: { color: "#a8d8ff" }, hovertemplate: "%{x}<br>%{y:.2f} ms<extra></extra>" }]} layout={{ yaxis: { title: { text: "Ping (ms)" } }, xaxis: { title: { text: "Tanggal" } } }} /></section></section>
    <div className="section-header"><h2>Detail Rollup</h2><CsvExport filename="daily-summary.csv" columns={["Tanggal", "Device", "Tipe", "Sample", "Ping sample", "Down", "Uptime", "Rata-rata ping", "Packet loss", "Update WIB"]} rows={data.items.map((item) => [item.rollup_date, item.device_name, item.device_type, item.total_samples, item.ping_samples, item.down_count, value(item.uptime_percentage, "%"), value(item.average_ping_ms, " ms"), value(item.average_packet_loss_percent, "%"), formatWib(item.updated_at)])} /></div>
    <DataTable columns={[{ key: "date", label: "Tanggal", render: (item) => item.rollup_date }, { key: "device", label: "Device", render: (item) => item.device_name }, { key: "type", label: "Tipe", render: (item) => item.device_type ?? "-" }, { key: "samples", label: "Sample", render: (item) => item.total_samples }, { key: "ping", label: "Ping sample", render: (item) => item.ping_samples }, { key: "down", label: "Down", render: (item) => item.down_count }, { key: "uptime", label: "Uptime", render: (item) => value(item.uptime_percentage, "%") }, { key: "avg", label: "Avg ping", render: (item) => value(item.average_ping_ms, " ms") }, { key: "minmax", label: "Min / Max ping", render: (item) => `${value(item.min_ping_ms)} / ${value(item.max_ping_ms)} ms` }, { key: "loss", label: "Packet loss", render: (item) => value(item.average_packet_loss_percent, "%") }, { key: "jitter", label: "Avg / Max jitter", render: (item) => `${value(item.average_jitter_ms)} / ${value(item.max_jitter_ms)} ms` }, { key: "updated", label: "Terakhir update (WIB)", render: (item) => formatWib(item.updated_at) }]} rows={data.items} />
    <Pagination offset={offset} limit={limit} total={data.meta.total} onChange={setOffset} />
  </main>;
}
