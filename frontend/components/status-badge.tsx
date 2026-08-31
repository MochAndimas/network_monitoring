import { statusLabel, statusTone, type StatusValue } from "@/lib/presentation";

export function StatusBadge({ value }: { value: StatusValue }) {
  return <span className={`status-badge ${statusTone(value)}`}>{statusLabel(value)}</span>;
}
