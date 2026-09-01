"use client";

import { useState } from "react";
import { DataTable } from "@/components/ui/data-table";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { DeviceDraft, DeviceTypeOption } from "./types";

type ImportError = { row: number; error: string };

function csvRows(source: string) {
  const rows: string[][] = []; let row: string[] = []; let cell = ""; let quoted = false;
  for (let index = 0; index < source.length; index += 1) { const char = source[index]; const next = source[index + 1]; if (char === '"' && quoted && next === '"') { cell += char; index += 1; } else if (char === '"') quoted = !quoted; else if (char === "," && !quoted) { row.push(cell.trim()); cell = ""; } else if ((char === "\n" || char === "\r") && !quoted) { if (char === "\r" && next === "\n") index += 1; row.push(cell.trim()); if (row.some(Boolean)) rows.push(row); row = []; cell = ""; } else cell += char; }
  row.push(cell.trim()); if (row.some(Boolean)) rows.push(row); return rows;
}

function activeValue(value: string) { const normalized = value.trim().toLowerCase(); if (["", "1", "true", "yes", "y", "aktif", "active"].includes(normalized)) return true; if (["0", "false", "no", "n", "nonaktif", "inactive"].includes(normalized)) return false; return null; }

function validate(source: string, types: DeviceTypeOption[], existingIps: Set<string>) {
  const [header = [], ...rows] = csvRows(source); const columns = new Map(header.map((name, index) => [name.toLowerCase(), index])); const missing = ["name", "ip_address", "device_type", "site"].filter((name) => !columns.has(name));
  if (missing.length) return { valid: [] as DeviceDraft[], errors: [{ row: 1, error: `Kolom wajib hilang: ${missing.join(", ")}` }] };
  const valid: DeviceDraft[] = []; const errors: ImportError[] = []; const seen = new Set<string>(); const typeValues = new Set(types.map((item) => item.value));
  rows.forEach((row, index) => { const field = (name: string) => row[columns.get(name) ?? -1]?.trim() ?? ""; const ip = field("ip_address"); const enabled = activeValue(field("is_active")); const issues: string[] = [];
    if (!field("name")) issues.push("name kosong"); if (!/^((25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(25[0-5]|2[0-4]\d|1?\d?\d)$/.test(ip)) issues.push("ip_address tidak valid"); if (seen.has(ip)) issues.push("ip_address duplikat di file"); if (existingIps.has(ip)) issues.push("ip_address sudah ada di inventory"); if (!typeValues.has(field("device_type"))) issues.push("device_type tidak didukung"); if (!field("site")) issues.push("site wajib diisi"); if (enabled === null) issues.push("is_active harus true/false atau kosong"); seen.add(ip);
    if (issues.length) errors.push({ row: index + 2, error: issues.join("; ") }); else valid.push({ name: field("name"), ip_address: ip, device_type: field("device_type"), site: field("site"), location: field("location") || null, description: field("description") || null, is_active: enabled ?? true }); });
  return { valid, errors };
}

export function DeviceImport({ types, existingIps, onComplete }: { types: DeviceTypeOption[]; existingIps: Set<string>; onComplete: () => Promise<void> }) {
  const [preview, setPreview] = useState<{ valid: DeviceDraft[]; errors: ImportError[] }>(); const [busy, setBusy] = useState(false); const [result, setResult] = useState<string>();
  const readFile = async (file: File | undefined) => { setResult(undefined); if (!file) return setPreview(undefined); setPreview(validate(await file.text(), types, existingIps)); };
  const importValid = async () => { if (!preview?.valid.length) return; setBusy(true); let succeeded = 0; const failures: ImportError[] = []; for (const [index, draft] of preview.valid.entries()) try { await apiFetch("/devices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) }); succeeded += 1; } catch (error) { failures.push({ row: index + 1, error: error instanceof ApiError ? error.message : "Gagal diimport" }); } setBusy(false); setResult(`Import selesai: ${succeeded} berhasil, ${failures.length} gagal.`); setPreview({ valid: [], errors: failures }); await onComplete(); };
  return <section><div className="section-header"><h2>Import CSV</h2></div><p>Kolom wajib: <code>name</code>, <code>ip_address</code>, <code>device_type</code>, <code>site</code>. Opsional: location, description, is_active.</p><input type="file" accept=".csv,text/csv" onChange={(event) => void readFile(event.target.files?.[0])} />{preview ? <><p>{preview.valid.length} baris valid, {preview.errors.length} baris bermasalah.</p>{preview.errors.length ? <DataTable columns={[{ key: "row", label: "Baris", render: (item) => item.row }, { key: "error", label: "Error", render: (item) => item.error }]} rows={preview.errors} /> : null}{preview.valid.length ? <button onClick={() => void importValid()} disabled={busy}>{busy ? "Mengimport…" : `Import ${preview.valid.length} device valid`}</button> : null}</> : null}{result ? <p role="status">{result}</p> : null}</section>;
}
