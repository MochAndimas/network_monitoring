const WIB_FORMATTER = new Intl.DateTimeFormat("id-ID", {
  dateStyle: "medium", timeStyle: "medium", timeZone: "Asia/Jakarta"
});

export function formatWib(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : WIB_FORMATTER.format(date);
}

export function statusLabel(value: string | null | undefined): string {
  const raw = String(value ?? "unknown").trim().toLowerCase();
  const labels: Record<string, string> = { up: "Up", ok: "OK", warning: "Warning", down: "Down", error: "Error", unknown: "Unknown" };
  return labels[raw] ?? raw.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
