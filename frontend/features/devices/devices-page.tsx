"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { apiFetch, ApiError, withQuery } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { PageHeader } from "@/components/ui/page-header";
import { MetaStrip } from "@/components/ui/meta-strip";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { CsvExport } from "@/components/ui/csv-export";
import { StatusBadge } from "@/components/ui/status-badge";
import { FreshnessLabel } from "@/components/ui/freshness-label";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { PermissionGate } from "@/components/ui/permission-gate";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { DeviceForm } from "./device-form";
import type { Device, DeviceDraft, DevicePage, DeviceTypeOption } from "./types";

const LIMIT = 50;
const invalidateDevices = (client: ReturnType<typeof useQueryClient>) => client.invalidateQueries({ queryKey: ["devices"] });

function initialOffset(value: string | null) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

export function DevicesPage() {
  const queryClient = useQueryClient(); const router = useRouter(); const pathname = usePathname(); const searchParams = useSearchParams();
  const [tab, setTab] = useState<"inventory" | "manage">(() => searchParams.get("tab") === "manage" ? "manage" : "inventory");
  const [search, setSearch] = useState(() => searchParams.get("q") ?? ""); const [type, setType] = useState(() => searchParams.get("type") ?? ""); const [status, setStatus] = useState(() => searchParams.get("status") ?? ""); const [activeOnly, setActiveOnly] = useState(() => searchParams.get("active") === "true"); const [offset, setOffset] = useState(() => initialOffset(searchParams.get("offset")));
  const [editing, setEditing] = useState<Device | null | "new">(null); const [deleting, setDeleting] = useState<Device | null>(null); const [mutationError, setMutationError] = useState<string>();
  const devices = useQuery({ queryKey: ["devices", { search, type, status, activeOnly, offset }], queryFn: () => apiFetch<DevicePage>(withQuery("/devices/paged", { search, device_type: type, latest_status: status, active_only: activeOnly, limit: LIMIT, offset })) });
  const types = useQuery({ queryKey: ["device-types"], queryFn: () => apiFetch<DeviceTypeOption[]>("/devices/meta/types"), staleTime: Infinity });
  const summary = useQuery({ queryKey: ["device-summary"], queryFn: () => apiFetch<Record<string, number>>("/devices/status-summary") });
  const save = useMutation({ mutationFn: ({ device, draft }: { device: Device | null | "new"; draft: DeviceDraft }) => apiFetch<Device>(device && device !== "new" ? `/devices/${device.id}` : "/devices", { method: device && device !== "new" ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) }), onSuccess: async () => { await invalidateDevices(queryClient); setEditing(null); }, onError: (error) => setMutationError(error instanceof ApiError ? error.message : "Gagal menyimpan device.") });
  const remove = useMutation({ mutationFn: (device: Device) => apiFetch<void>(`/devices/${device.id}`, { method: "DELETE" }), onSuccess: async () => { await invalidateDevices(queryClient); setDeleting(null); }, onError: (error) => setMutationError(error instanceof ApiError ? error.message : "Gagal menghapus device.") });
  const resetPage = () => setOffset(0);
  useEffect(() => {
    const params = new URLSearchParams();
    if (tab !== "inventory") params.set("tab", tab);
    if (search) params.set("q", search);
    if (type) params.set("type", type);
    if (status) params.set("status", status);
    if (activeOnly) params.set("active", "true");
    if (offset) params.set("offset", String(offset));
    const next = params.toString();
    if (next !== searchParams.toString()) router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
  }, [activeOnly, offset, pathname, router, search, searchParams, status, tab, type]);
  if (devices.isPending || types.isPending) return <LoadingState />; if (devices.isError) return <ErrorState message="Inventaris device tidak dapat dimuat." onRetry={() => void devices.refetch()} />;
  const rows = devices.data.items; const counts = summary.data ?? {}; const deviceTypes = types.data ?? [];
  const saveDevice = async (draft: DeviceDraft) => { setMutationError(undefined); await save.mutateAsync({ device: editing, draft }); };
  return <main className="app-page"><PageHeader title="Devices" description="Inventory perangkat dan pengelolaan device melalui FastAPI." />
    <MetaStrip items={[{ label: "Total hasil", value: devices.data.meta.total ?? "—" }, { label: "Auto refresh", value: "Manual" }, { label: "Terakhir dirender", value: formatWib(new Date().toISOString()) }]} />
    <div className="tab-list" role="tablist"><button className={tab === "inventory" ? "tab-active" : ""} onClick={() => setTab("inventory")} role="tab" aria-selected={tab === "inventory"}>Inventory</button><PermissionGate><button className={tab === "manage" ? "tab-active" : ""} onClick={() => setTab("manage")} role="tab" aria-selected={tab === "manage"}>Kelola</button></PermissionGate></div>
    <MetricGrid>{[["Total", counts.total ?? devices.data.meta.total ?? 0], ["Aktif", counts.active ?? 0], ["Down", counts.down ?? 0], ["Warning", counts.warning ?? 0]].map(([label, value]) => <MetricCard key={String(label)} label={String(label)} value={String(value)} />)}</MetricGrid>
    <div className="filter-panel"><label>Cari<input value={search} placeholder="Nama, IP, site, lokasi" onChange={(event) => { setSearch(event.target.value); resetPage(); }} /></label><label>Tipe<select value={type} onChange={(event) => { setType(event.target.value); resetPage(); }}><option value="">Semua tipe</option>{deviceTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Status<select value={status} onChange={(event) => { setStatus(event.target.value); resetPage(); }}><option value="">Semua status</option>{["up", "warning", "down", "error", "unknown"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label className="checkbox">Hanya aktif<input type="checkbox" checked={activeOnly} onChange={(event) => { setActiveOnly(event.target.checked); resetPage(); }} /></label></div>
    <div className="section-header"><h2>{tab === "manage" ? "Kelola Device" : "Inventory Device"}</h2><div className="inline-actions"><CsvExport filename="devices.csv" columns={["Nama", "IP", "Tipe", "Site", "Lokasi", "Status", "Freshness", "Aktif"]} rows={rows.map((item) => [item.name, item.ip_address, item.device_type, item.site, item.location, item.latest_status, item.latest_checked_at, item.is_active ? "Ya" : "Tidak"])} />{tab === "manage" ? <button onClick={() => { setMutationError(undefined); setEditing("new"); }}>Tambah device</button> : null}</div></div>
    <DataTable columns={[{ key: "name", label: "Nama", render: (item) => item.name }, { key: "ip", label: "IP", render: (item) => item.ip_address }, { key: "type", label: "Tipe", render: (item) => item.device_type }, { key: "site", label: "Site", render: (item) => item.site ?? "-" }, { key: "location", label: "Lokasi", render: (item) => item.location ?? "-" }, { key: "status", label: "Status terakhir", render: (item) => <StatusBadge value={item.latest_status} /> }, { key: "fresh", label: "Freshness", render: (item) => <FreshnessLabel checkedAt={item.latest_checked_at} /> }, { key: "active", label: "Aktif", render: (item) => item.is_active ? "Ya" : "Tidak" }, ...(tab === "manage" ? [{ key: "actions", label: "Aksi", render: (item: Device) => <div className="inline-actions"><button className="button-secondary" onClick={() => { setMutationError(undefined); setEditing(item); }}>Edit</button><button className="button-danger" onClick={() => { setMutationError(undefined); setDeleting(item); }}>Hapus</button></div> }] : [])]} rows={rows} />
    <Pagination offset={offset} limit={LIMIT} total={devices.data.meta.total} onChange={setOffset} />
    {editing ? <div className="dialog-backdrop"><section className="dialog" role="dialog" aria-modal="true"><h2>{editing === "new" ? "Tambah Device" : `Edit ${editing.name}`}</h2><DeviceForm device={editing === "new" ? undefined : editing} types={deviceTypes} pending={save.isPending} error={mutationError} onSubmit={saveDevice} onCancel={() => setEditing(null)} /></section></div> : null}
    {deleting ? <ConfirmDialog title="Hapus device" confirmLabel="Hapus device" pending={remove.isPending} onClose={() => setDeleting(null)} onConfirm={() => void remove.mutateAsync(deleting)}><p>Hapus <strong>{deleting.name}</strong>? Tindakan ini tidak dapat dibatalkan.</p>{mutationError ? <p className="form-error">{mutationError}</p> : null}</ConfirmDialog> : null}
  </main>;
}
