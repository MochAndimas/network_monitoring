"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { DataTable } from "@/components/ui/data-table";
import { PlotlyChart } from "@/components/charts/plotly-chart";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PermissionGate } from "@/components/ui/permission-gate";
import { ApiError, apiFetch } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";

type Threshold = { id: number; key: string; value: number; description: string | null };
type Override = { id: number; threshold_key: string; value: number; device_id: number | null; device_type: string | null; site: string | null; description: string | null; is_active: boolean; created_at: string };
type Window = { id: number; name: string; device_id: number | null; site: string | null; starts_at: string; ends_at: string; reason: string | null; is_active: boolean };

type ThresholdSort = "key" | "value" | "category";
type OverrideScope = "site" | "device_type" | "device_id";
type MaintenanceScope = "site" | "device_id";

function thresholdCategory(key: string) {
  const separator = key.includes("_") ? "_" : key.includes(":") ? ":" : "";
  return separator ? key.split(separator, 1)[0] : "general";
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 4 }).format(value);
}

export function ThresholdsPage() {
  const [tab, setTab] = useState<"global" | "overrides" | "maintenance">("global");
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ThresholdSort>("key");
  const [editing, setEditing] = useState<Threshold | null>(null);
  const [override, setOverride] = useState({ threshold_key: "", value: "", site: "", device_type: "", description: "" });
  const [overrideScope, setOverrideScope] = useState<OverrideScope>("site");
  const [overrideScopeValue, setOverrideScopeValue] = useState("");
  const [windowForm, setWindowForm] = useState({ name: "", site: "", starts_at: "", ends_at: "", reason: "" });
  const [maintenanceScope, setMaintenanceScope] = useState<MaintenanceScope>("site");
  const [maintenanceScopeValue, setMaintenanceScopeValue] = useState("");
  const client = useQueryClient();
  const thresholds = useQuery({ queryKey: ["thresholds"], queryFn: () => apiFetch<Threshold[]>("/thresholds") });
  const overrides = useQuery({ queryKey: ["threshold-overrides"], queryFn: () => apiFetch<Override[]>("/thresholds/overrides") });
  const windows = useQuery({ queryKey: ["maintenance"], queryFn: () => apiFetch<Window[]>("/thresholds/maintenance-windows") });
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["thresholds"] }), client.invalidateQueries({ queryKey: ["threshold-overrides"] }), client.invalidateQueries({ queryKey: ["maintenance"] })]);
  const update = useMutation({ mutationFn: (item: Threshold) => apiFetch(`/thresholds/${item.key}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: item.value }) }), onSuccess: refresh });
  const createOverride = useMutation({ mutationFn: () => {
    const value = Number(override.value);
    if (!override.threshold_key || !Number.isFinite(value) || !overrideScopeValue.trim()) throw new Error("Threshold, nilai, dan scope wajib diisi.");
    const deviceId = Number(overrideScopeValue);
    if (overrideScope === "device_id" && (!Number.isInteger(deviceId) || deviceId <= 0)) throw new Error("Device ID harus berupa bilangan bulat positif.");
    const scope = overrideScope === "device_id" ? { device_id: deviceId } : { [overrideScope]: overrideScopeValue.trim() };
    return apiFetch("/thresholds/overrides", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ threshold_key: override.threshold_key, value, description: override.description || null, ...scope }) });
  }, onSuccess: () => { setOverride({ threshold_key: "", value: "", site: "", device_type: "", description: "" }); setOverrideScopeValue(""); return refresh(); } });
  const createWindow = useMutation({ mutationFn: () => {
    if (!windowForm.name || !windowForm.starts_at || !windowForm.ends_at || !maintenanceScopeValue.trim()) throw new Error("Nama, scope, waktu mulai, dan waktu selesai wajib diisi.");
    if (new Date(windowForm.starts_at) >= new Date(windowForm.ends_at)) throw new Error("Waktu selesai harus setelah waktu mulai.");
    const deviceId = Number(maintenanceScopeValue);
    if (maintenanceScope === "device_id" && (!Number.isInteger(deviceId) || deviceId <= 0)) throw new Error("Device ID harus berupa bilangan bulat positif.");
    const scope = maintenanceScope === "device_id" ? { device_id: deviceId } : { site: maintenanceScopeValue.trim() };
    return apiFetch("/thresholds/maintenance-windows", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: windowForm.name, reason: windowForm.reason || null, starts_at: new Date(windowForm.starts_at).toISOString(), ends_at: new Date(windowForm.ends_at).toISOString(), ...scope }) });
  }, onSuccess: () => { setWindowForm({ name: "", site: "", starts_at: "", ends_at: "", reason: "" }); setMaintenanceScopeValue(""); return refresh(); } });
  const deactivate = useMutation({ mutationFn: ({ path }: { path: string }) => apiFetch(path, { method: "DELETE" }), onSuccess: refresh });
  if (thresholds.isPending || overrides.isPending || windows.isPending) return <LoadingState />;
  if (thresholds.isError || overrides.isError || windows.isError) return <ErrorState message="Policy threshold tidak dapat dimuat." onRetry={() => { void thresholds.refetch(); void overrides.refetch(); void windows.refetch(); }} />;
  const categories = [...new Set(thresholds.data.map((item) => thresholdCategory(item.key)))].sort();
  const filteredThresholds = thresholds.data.filter((item) => {
    const matchesCategory = category === "all" || thresholdCategory(item.key) === category;
    const needle = search.trim().toLowerCase();
    return matchesCategory && (!needle || item.key.toLowerCase().includes(needle) || item.description?.toLowerCase().includes(needle));
  }).sort((left, right) => {
    if (sort === "value") return right.value - left.value || left.key.localeCompare(right.key);
    if (sort === "category") return thresholdCategory(left.key).localeCompare(thresholdCategory(right.key)) || left.key.localeCompare(right.key);
    return left.key.localeCompare(right.key);
  });
  const values = filteredThresholds.map((item) => item.value);
  const categorySummary = categories.map((name) => ({ category: name, count: filteredThresholds.filter((item) => thresholdCategory(item.key) === name).length })).filter((item) => item.count > 0);
  const mutationMessage = [update.error, createOverride.error, createWindow.error, deactivate.error].find(Boolean);
  const mutationError = mutationMessage instanceof ApiError || mutationMessage instanceof Error ? mutationMessage.message : null;
  return <main className="app-page"><PageHeader title="Thresholds" description="Policy global, override terarah, dan maintenance window." /><div className="tab-list">{(["global", "overrides", "maintenance"] as const).map((item) => <button key={item} className={tab === item ? "tab-active" : ""} onClick={() => setTab(item)}>{item === "global" ? "Global" : item === "overrides" ? "Overrides" : "Maintenance"}</button>)}</div>{mutationError ? <p className="form-error" role="alert">{mutationError}</p> : null}
    {tab === "global" ? <>
      <div className="filter-panel"><label>Kategori<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">Semua kategori</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>Cari<input value={search} placeholder="Key atau deskripsi threshold" onChange={(event) => setSearch(event.target.value)} /></label><label>Urutkan<select value={sort} onChange={(event) => setSort(event.target.value as ThresholdSort)}><option value="key">Key (A–Z)</option><option value="value">Nilai tertinggi</option><option value="category">Kategori</option></select></label></div>
      <MetricGrid columns={4}><MetricCard label="Total threshold" value={filteredThresholds.length} /><MetricCard label="Jumlah kategori" value={categorySummary.length} /><MetricCard label="Nilai rata-rata" value={formatNumber(values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0)} /><MetricCard label="Nilai maksimum" value={formatNumber(values.length ? Math.max(...values) : 0)} /></MetricGrid>
      {categorySummary.length ? <section><div className="section-header"><h2>Ringkasan Kategori</h2></div><PlotlyChart ariaLabel="Distribusi threshold per kategori" data={[{ type: "bar", orientation: "h", x: categorySummary.map((item) => item.count), y: categorySummary.map((item) => item.category), marker: { color: "#4aa3f5" }, hovertemplate: "%{y}: %{x}<extra></extra>" }]} layout={{ height: 260, xaxis: { title: { text: "Jumlah threshold" } }, yaxis: { autorange: "reversed" } }} /></section> : null}
      <DataTable columns={[{ key: "category", label: "Kategori", render: (item) => thresholdCategory(item.key) }, { key: "key", label: "Key", render: (item) => item.key }, { key: "value", label: "Nilai", render: (item) => formatNumber(item.value) }, { key: "description", label: "Deskripsi", render: (item) => item.description ?? "-" }, { key: "action", label: "Aksi", render: (item) => <PermissionGate><button className="button-secondary" onClick={() => setEditing({ ...item })}>Edit</button></PermissionGate> }]} rows={filteredThresholds} emptyLabel="Tidak ada threshold yang cocok dengan filter." />{editing ? <PermissionGate><form className="device-form" onSubmit={(event) => { event.preventDefault(); update.mutate(editing); setEditing(null); }}><label>Threshold<input type="number" step="any" value={editing.value} onChange={(event) => setEditing({ ...editing, value: Number(event.target.value) })} /></label><div className="inline-actions"><button type="submit">Simpan</button><button type="button" className="button-secondary" onClick={() => setEditing(null)}>Batal</button></div></form></PermissionGate> : null}</> : null}
    {tab === "overrides" ? <><PermissionGate><form className="device-form" onSubmit={(event) => { event.preventDefault(); createOverride.mutate(); }}><label>Threshold key<select value={override.threshold_key} onChange={(event) => setOverride({ ...override, threshold_key: event.target.value })} required><option value="">Pilih threshold</option>{thresholds.data.map((item) => <option key={item.key} value={item.key}>{item.key}</option>)}</select></label><label>Nilai<input type="number" step="any" value={override.value} onChange={(event) => setOverride({ ...override, value: event.target.value })} required /></label><label>Jenis scope<select value={overrideScope} onChange={(event) => { setOverrideScope(event.target.value as OverrideScope); setOverrideScopeValue(""); }}><option value="site">Site</option><option value="device_type">Tipe device</option><option value="device_id">Device ID</option></select></label><label>{overrideScope === "device_id" ? "Device ID" : overrideScope === "site" ? "Site" : "Tipe device"}<input type={overrideScope === "device_id" ? "number" : "text"} min={overrideScope === "device_id" ? 1 : undefined} value={overrideScopeValue} onChange={(event) => setOverrideScopeValue(event.target.value)} required /></label><label className="form-span-2">Deskripsi<input value={override.description} onChange={(event) => setOverride({ ...override, description: event.target.value })} /></label><button type="submit" disabled={createOverride.isPending}>{createOverride.isPending ? "Menyimpan…" : "Tambah override"}</button></form></PermissionGate><DataTable columns={[{ key: "key", label: "Threshold", render: (item) => item.threshold_key }, { key: "value", label: "Nilai", render: (item) => item.value }, { key: "scope", label: "Scope", render: (item) => item.site ?? item.device_type ?? item.device_id ?? "Global" }, { key: "status", label: "Status", render: (item) => item.is_active ? "Aktif" : "Nonaktif" }, { key: "action", label: "Aksi", render: (item) => item.is_active ? <PermissionGate><button className="button-danger" onClick={() => deactivate.mutate({ path: `/thresholds/overrides/${item.id}` })}>Nonaktifkan</button></PermissionGate> : "-" }]} rows={overrides.data} /></> : null}
    {tab === "maintenance" ? <><PermissionGate><form className="device-form" onSubmit={(event) => { event.preventDefault(); createWindow.mutate(); }}><label>Nama<input value={windowForm.name} onChange={(event) => setWindowForm({ ...windowForm, name: event.target.value })} required /></label><label>Jenis scope<select value={maintenanceScope} onChange={(event) => { setMaintenanceScope(event.target.value as MaintenanceScope); setMaintenanceScopeValue(""); }}><option value="site">Site</option><option value="device_id">Device ID</option></select></label><label>{maintenanceScope === "device_id" ? "Device ID" : "Site"}<input type={maintenanceScope === "device_id" ? "number" : "text"} min={maintenanceScope === "device_id" ? 1 : undefined} value={maintenanceScopeValue} onChange={(event) => setMaintenanceScopeValue(event.target.value)} required /></label><label>Mulai<input type="datetime-local" value={windowForm.starts_at} onChange={(event) => setWindowForm({ ...windowForm, starts_at: event.target.value })} required /></label><label>Selesai<input type="datetime-local" value={windowForm.ends_at} onChange={(event) => setWindowForm({ ...windowForm, ends_at: event.target.value })} required /></label><label className="form-span-2">Alasan<input value={windowForm.reason} onChange={(event) => setWindowForm({ ...windowForm, reason: event.target.value })} /></label><button type="submit" disabled={createWindow.isPending}>{createWindow.isPending ? "Menyimpan…" : "Tambah maintenance"}</button></form></PermissionGate><DataTable columns={[{ key: "name", label: "Nama", render: (item) => item.name }, { key: "site", label: "Scope", render: (item) => item.site ?? item.device_id ?? "-" }, { key: "start", label: "Mulai", render: (item) => formatWib(item.starts_at) }, { key: "end", label: "Selesai", render: (item) => formatWib(item.ends_at) }, { key: "status", label: "Status", render: (item) => item.is_active ? "Aktif" : "Nonaktif" }, { key: "action", label: "Aksi", render: (item) => item.is_active ? <PermissionGate><button className="button-danger" onClick={() => deactivate.mutate({ path: `/thresholds/maintenance-windows/${item.id}` })}>Nonaktifkan</button></PermissionGate> : "-" }]} rows={windows.data} /></> : null}
  </main>;
}
