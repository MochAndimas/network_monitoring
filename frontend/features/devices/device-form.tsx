"use client";

import { FormEvent, useState } from "react";
import type { Device, DeviceDraft, DeviceTypeOption } from "./types";

const emptyDraft: DeviceDraft = { name: "", ip_address: "", device_type: "", site: "", location: "", description: "", is_active: true };
function draftFrom(device?: Device): DeviceDraft { return device ? { name: device.name, ip_address: device.ip_address, device_type: device.device_type, site: device.site ?? "", location: device.location ?? "", description: device.description ?? "", is_active: device.is_active } : emptyDraft; }

export function DeviceForm({ device, types, pending, error, onSubmit, onCancel }: { device?: Device; types: DeviceTypeOption[]; pending: boolean; error?: string; onSubmit: (draft: DeviceDraft) => Promise<void>; onCancel: () => void }) {
  const [draft, setDraft] = useState<DeviceDraft>(() => draftFrom(device));
  const set = <Key extends keyof DeviceDraft>(key: Key, value: DeviceDraft[Key]) => setDraft((previous) => ({ ...previous, [key]: value }));
  async function submit(event: FormEvent) { event.preventDefault(); await onSubmit({ ...draft, location: draft.location || null, description: draft.description || null }); }
  return <form className="device-form" onSubmit={(event) => void submit(event)}>
    {error ? <p className="form-error form-span-2" role="alert">{error}</p> : null}
    <label>Nama<input required value={draft.name} onChange={(event) => set("name", event.target.value)} /></label>
    <label>IP address<input required inputMode="decimal" value={draft.ip_address} onChange={(event) => set("ip_address", event.target.value)} /></label>
    <label>Tipe<select required value={draft.device_type} onChange={(event) => set("device_type", event.target.value)}><option value="">Pilih tipe</option>{types.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select></label>
    <label>Site<input required value={draft.site ?? ""} onChange={(event) => set("site", event.target.value)} /></label>
    <label>Lokasi<input value={draft.location ?? ""} onChange={(event) => set("location", event.target.value)} /></label>
    <label className="checkbox">Aktif<input type="checkbox" checked={draft.is_active} onChange={(event) => set("is_active", event.target.checked)} /></label>
    <label className="form-span-2">Deskripsi<textarea rows={3} value={draft.description ?? ""} onChange={(event) => set("description", event.target.value)} /></label>
    <div className="form-span-2 inline-actions"><button className="button-secondary" type="button" disabled={pending} onClick={onCancel}>Batal</button><button type="submit" disabled={pending}>{pending ? "Menyimpan…" : device ? "Simpan perubahan" : "Tambah device"}</button></div>
  </form>;
}
