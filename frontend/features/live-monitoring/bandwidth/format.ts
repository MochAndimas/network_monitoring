import { formatWib } from "@/lib/formatters";
import type { ReportRange, UsageRow } from "./types";

const UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"];

export function formatBytes(raw: string | bigint): string {
  const bytes = BigInt(raw);
  let divisor = 1n;
  let unit = 0;
  while (bytes >= divisor * 1024n && unit < UNITS.length - 1) {
    divisor *= 1024n;
    unit++;
  }
  if (unit === 0) return `${bytes.toLocaleString("id-ID")} B`;
  const scaled = (bytes * 100n + divisor / 2n) / divisor;
  return `${(scaled / 100n).toLocaleString("id-ID")},${String(scaled % 100n).padStart(2, "0")} ${UNITS[unit]}`;
}

export function exactBytes(raw: string): string {
  return `${BigInt(raw).toLocaleString("id-ID")} byte`;
}

export function formatEpochNs(raw: string | undefined): string {
  if (!raw) return "—";
  // Only the display timestamp is reduced to milliseconds, never byte counters.
  const date = new Date(Number(BigInt(raw) / 1_000_000n));
  return Number.isNaN(date.getTime()) ? "—" : formatWib(date.toISOString());
}

export function wibToday(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return (
    Number.isFinite(timestamp) &&
    new Date(timestamp).toISOString().slice(0, 10) === value
  );
}

export function rangeError({ start, end }: ReportRange): string | null {
  if (!validDate(start) || !validDate(end))
    return "Isi tanggal mulai dan akhir yang valid.";
  const days =
    (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) /
    86_400_000;
  if (days < 0) return "Tanggal mulai tidak boleh melewati tanggal akhir.";
  if (days >= 31)
    return "Pilih rentang maksimal 31 hari, termasuk tanggal mulai dan akhir.";
  return null;
}

export function summarizeUsage(rows: readonly UsageRow[]) {
  return rows.reduce(
    (sum, row) => ({
      upload: sum.upload + BigInt(row.upload_bytes),
      download: sum.download + BigInt(row.download_bytes),
      total: sum.total + BigInt(row.total_bytes),
      estimated: sum.estimated + BigInt(row.estimated_bytes),
      unresolved: sum.unresolved + BigInt(row.unresolved_bytes),
      updated:
        BigInt(row.updated_ns) > sum.updated
          ? BigInt(row.updated_ns)
          : sum.updated,
    }),
    {
      upload: 0n,
      download: 0n,
      total: 0n,
      estimated: 0n,
      unresolved: 0n,
      updated: 0n,
    },
  );
}

/** Convert only the bounded visual ratio, not either original byte value. */
export function barPercent(value: string, maximum: string): number {
  const max = BigInt(maximum);
  return max === 0n ? 0 : Number((BigInt(value) * 10_000n) / max) / 100;
}
