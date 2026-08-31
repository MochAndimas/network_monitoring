"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { ApiError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const REFRESH_INTERVAL_MS = 15_000;

type Status = "normal" | "ok" | "warning" | "down" | "error" | "critical" | "unknown" | string;

type OverviewPayload = {
  summary: { internet_status: Status; mikrotik_status: Status; server_status: Status; active_alerts: number };
  device_counts: { total: number; active: number; inactive: number; statuses: Record<string, number>; latest_check_at: string | null };
  alert_severity_summary: Record<string, number>;
  alerts: Array<{ id?: number; created_at: string; device_name: string; severity: Status; message: string; site?: string | null }>;
  incidents: Array<{ id?: number; started_at: string; device_name: string; summary: string; status: Status; site?: string | null }>;
  latest_snapshot: { items: Array<{ id: number; device_id: number; device_name: string; metric_name: string; metric_value: string; status: Status | null; unit: string | null; checked_at: string }> };
  problem_devices: Array<{ id: number; name: string; ip_address: string; device_type: string; site: string | null; latest_status: Status; latest_checked_at: string | null }>;
};

const statusLabel = (value: Status | null | undefined) => {
  const normalized = String(value || "unknown").replaceAll("_", " ").trim();
  return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : "Unknown";
};

const statusTone = (value: Status | null | undefined) => {
  const normalized = String(value || "unknown").toLowerCase();
  if (["critical", "error", "down"].includes(normalized)) return "critical";
  if (["warning", "degraded"].includes(normalized)) return "warning";
  if (["normal", "ok", "up", "active", "resolved"].includes(normalized)) return "normal";
  return "unknown";
};

const formatWib = (value: string | null | undefined) => value
  ? new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "medium", timeZone: "Asia/Jakarta" }).format(new Date(value)) + " WIB"
  : "-";

const freshness = (value: string | null | undefined) => {
  if (!value) return "Belum ada data";
  const ageMinutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60_000));
  if (ageMinutes < 2) return "Fresh";
  if (ageMinutes < 5) return `${ageMinutes} menit lalu`;
  if (ageMinutes < 60) return `Stale ${ageMinutes} menit`;
  return `Stale ${Math.floor(ageMinutes / 60)} jam`;
};

function downloadCsv(filename: string, headers: string[], rows: string[][]) {
  const quote = (value: string) => `"${value.replaceAll('"', '""')}"`;
  const csv = [headers, ...rows].map((row) => row.map((cell) => quote(cell)).join(",")).join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function StatusBadge({ value }: { value: Status | null | undefined }) {
  return <span className={`status-badge ${statusTone(value)}`}>{statusLabel(value)}</span>;
}

function OverviewTable({ title, children, onDownload, empty }: { title: string; children: React.ReactNode; onDownload?: () => void; empty?: boolean }) {
  return <section className="panel table-panel"><div className="section-heading"><h2>{title}</h2>{onDownload && <button className="button button-secondary button-inline" onClick={onDownload}>Download CSV</button>}</div>{empty ? <p className="empty-state">Belum ada data untuk ditampilkan.</p> : <div className="table-scroll"><table>{children}</table></div>}</section>;
}

export function OverviewDashboard() {
  const { ready, user, token } = useAuth();
  const [payload, setPayload] = useState<OverviewPayload | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(true);
  const [runningCycle, setRunningCycle] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      const data = await apiRequest<OverviewPayload>("/dashboard/overview-data", { cache: "no-store" }, token);
      setPayload(data);
      setUpdatedAt(new Date());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, "Koneksi ke backend gagal."));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!ready || !token) return;
    void load();
  }, [ready, token, load]);

  useEffect(() => {
    if (!autoRefresh || !token) return;
    const refresh = () => { if (!document.hidden) void load(); };
    const timer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [autoRefresh, load, token]);

  const severityChart = useMemo(() => {
    const entries = Object.entries(payload?.alert_severity_summary || {}).sort(([left], [right]) => left.localeCompare(right));
    return { labels: entries.map(([severity]) => statusLabel(severity)), values: entries.map(([, count]) => count) };
  }, [payload]);

  const runCycle = async () => {
    if (!token) return;
    setRunningCycle(true); setError(null);
    try { await apiRequest("/system/run-cycle", { method: "POST" }, token); await load(); }
    catch (caught) { setError(caught instanceof ApiError ? caught : new ApiError(0, "Monitoring cycle gagal dijalankan.")); }
    finally { setRunningCycle(false); }
  };

  if (!ready || !user) return <div className="login">Memulihkan sesi…</div>;
  const data = payload;
  const statuses = data?.device_counts.statuses || {};
  const problemDevices = data?.problem_devices || [];
  const alerts = data?.alerts || [];
  const incidents = data?.incidents || [];
  const snapshots = data?.latest_snapshot.items || [];

  return <AppShell>
    <header className="page-header"><div><h1 className="page-title">Overview</h1><p className="page-description">Ringkasan kesehatan jaringan dan prioritas operasional.</p></div><div className="header-actions"><label className="switch-label"><input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} /> Refresh otomatis (15 dtk)</label><button className="button button-secondary button-inline" onClick={() => void load()} disabled={loading}>{loading ? "Memuat…" : "Refresh"}</button>{user.role === "admin" && <button className="button button-inline" onClick={() => void runCycle()} disabled={runningCycle}>{runningCycle ? "Menjalankan…" : "Jalankan Cycle"}</button>}</div></header>
    <p className="meta-row">Terakhir diperbarui: {updatedAt ? formatWib(updatedAt.toISOString()) : "-"} · Pemeriksaan device terakhir: {formatWib(data?.device_counts.latest_check_at)}</p>
    {error && <div className="alert-box error-box"><div>{error.message}</div><button className="button button-secondary button-inline" onClick={() => void load()}>Coba lagi</button>{error.requestId && <small>Request ID: {error.requestId}</small>}</div>}
    {loading && !data ? <section className="panel">Memuat ringkasan operasional…</section> : <>
      <section><h2 className="section-title">Status Global</h2><div className="kpi-grid four"><Kpi label="Internet" value={<StatusBadge value={data?.summary.internet_status} />} href="/live-monitoring" /><Kpi label="MikroTik" value={<StatusBadge value={data?.summary.mikrotik_status} />} href="/live-monitoring" /><Kpi label="Server" value={<StatusBadge value={data?.summary.server_status} />} href="/live-monitoring" /><Kpi label="Alert Aktif" value={data?.summary.active_alerts ?? 0} href="/alerts" /></div></section>
      <section><h2 className="section-title">Snapshot Operasional</h2><div className="kpi-grid five"><Kpi label="Total Device" value={data?.device_counts.total ?? 0} href="/devices" /><Kpi label="Device Aktif" value={data?.device_counts.active ?? 0} href="/devices?active=true" /><Kpi label="Device Down" value={statuses.down || 0} href="/devices?status=down" /><Kpi label="Device Warning" value={statuses.warning || 0} href="/devices?status=warning" /><Kpi label="Insiden Aktif" value={incidents.length} href="/incidents?status=active" /></div></section>
      <div className="overview-split"><OverviewTable title="Device Perlu Perhatian" empty={!problemDevices.length} onDownload={() => downloadCsv("overview_problem_devices.csv", ["Device", "IP Address", "Tipe", "Site", "Status", "Freshness", "Pemeriksaan Terakhir (WIB)"], problemDevices.map((row) => [row.name, row.ip_address, row.device_type, row.site || "-", statusLabel(row.latest_status), freshness(row.latest_checked_at), formatWib(row.latest_checked_at)]))}><thead><tr><th>Device</th><th>IP Address</th><th>Tipe</th><th>Site</th><th>Status</th><th>Freshness</th></tr></thead><tbody>{problemDevices.map((row) => <tr key={row.id}><td><Link href={`/devices?search=${encodeURIComponent(row.name)}`}>{row.name}</Link></td><td>{row.ip_address}</td><td>{row.device_type}</td><td>{row.site || "-"}</td><td><StatusBadge value={row.latest_status} /></td><td>{freshness(row.latest_checked_at)}</td></tr>)}</tbody></OverviewTable>
        <section className="panel chart-panel"><div className="section-heading"><h2>Distribusi Tingkat Alert</h2><Link href="/alerts" className="text-link">Lihat alert</Link></div>{severityChart.values.length ? <Plot data={[{ type: "bar", orientation: "h", x: severityChart.values, y: severityChart.labels, marker: { color: "#748ffc" }, hovertemplate: "%{y}: %{x}<extra></extra>" }]} layout={{ autosize: true, height: 260, margin: { l: 90, r: 20, t: 10, b: 40 }, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { color: "#f5f7fb" }, xaxis: { title: { text: "Jumlah" }, gridcolor: "#2d3746", zerolinecolor: "#2d3746" }, yaxis: { automargin: true } }} config={{ displayModeBar: false, responsive: true }} style={{ width: "100%" }} /> : <p className="empty-state">Tidak ada alert aktif. Sistem dalam kondisi normal.</p>}</section></div>
      <div className="overview-split equal"><OverviewTable title="Alert Aktif Terbaru" empty={!alerts.length}><thead><tr><th>Dibuat (WIB)</th><th>Device</th><th>Tingkat</th><th>Pesan</th></tr></thead><tbody>{alerts.map((row, index) => <tr key={row.id || `${row.device_name}-${index}`}><td>{formatWib(row.created_at)}</td><td>{row.device_name}</td><td><StatusBadge value={row.severity} /></td><td>{row.message}</td></tr>)}</tbody></OverviewTable><OverviewTable title="Insiden Aktif" empty={!incidents.length}><thead><tr><th>Mulai (WIB)</th><th>Device</th><th>Ringkasan</th><th>Status</th></tr></thead><tbody>{incidents.map((row, index) => <tr key={row.id || `${row.device_name}-${index}`}><td>{formatWib(row.started_at)}</td><td>{row.device_name}</td><td>{row.id ? <Link href={`/incidents/${row.id}`}>{row.summary}</Link> : row.summary}</td><td><StatusBadge value={row.status} /></td></tr>)}</tbody></OverviewTable></div>
      <OverviewTable title="Snapshot Metric Terbaru" empty={!snapshots.length} onDownload={() => downloadCsv("overview_latest_metrics.csv", ["Checked At (WIB)", "Device", "Metrik", "Nilai", "Status", "Freshness"], snapshots.map((row) => [formatWib(row.checked_at), row.device_name, row.metric_name, `${row.metric_value}${row.unit ? ` ${row.unit}` : ""}`, statusLabel(row.status), freshness(row.checked_at)]))}><thead><tr><th>Checked At (WIB)</th><th>Device</th><th>Metrik</th><th>Nilai</th><th>Status</th><th>Freshness</th></tr></thead><tbody>{snapshots.map((row) => <tr key={row.id}><td>{formatWib(row.checked_at)}</td><td><Link href={`/live-monitoring?device_id=${row.device_id}`}>{row.device_name}</Link></td><td>{row.metric_name}</td><td>{row.metric_value}{row.unit ? ` ${row.unit}` : ""}</td><td><StatusBadge value={row.status} /></td><td>{freshness(row.checked_at)}</td></tr>)}</tbody></OverviewTable>
    </>}
  </AppShell>;
}

function Kpi({ label, value, href }: { label: string; value: React.ReactNode; href: string }) {
  return <Link href={href} className="kpi-card"><span>{label}</span><strong>{value}</strong><small>Lihat detail →</small></Link>;
}
