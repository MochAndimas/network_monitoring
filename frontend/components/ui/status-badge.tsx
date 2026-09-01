const STATUS_CLASS: Record<string, string> = {
  up: "success", ok: "success", active: "info", warning: "warning",
  down: "danger", error: "danger", critical: "danger", high: "danger", resolved: "muted"
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const text = String(value ?? "unknown").replaceAll("_", " ");
  return <span className={`status-badge status-${STATUS_CLASS[text.toLowerCase()] ?? "muted"}`}>{text}</span>;
}
