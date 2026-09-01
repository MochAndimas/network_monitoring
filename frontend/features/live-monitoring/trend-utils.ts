import type { MetricSample } from "./types";

const LABELS: Record<string, string> = {
  ping: "Ping Latency", packet_loss: "Packet Loss", jitter: "Jitter", cpu_percent: "CPU Usage",
  memory_percent: "Memory Usage", disk_percent: "Disk Usage", connected_clients: "Connected Clients",
  dhcp_active_leases: "DHCP Active Leases"
};

const MIKROTIK_DEFAULTS = ["ping", "packet_loss", "jitter", "cpu_percent"];
const NAS_DEFAULTS = ["ping", "packet_loss", "jitter", "cpu_percent", "memory_percent", "disk_percent"];

export function metricLabel(metricName: string) {
  return LABELS[metricName] ?? metricName.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function trendMetricNames(deviceType: string | undefined, metricNames: readonly string[], selectedMetric: string) {
  if (selectedMetric) return selectedMetric.startsWith("interface:") || selectedMetric.startsWith("queue:") || selectedMetric.startsWith("firewall:") ? [] : [selectedMetric];
  const preferred = deviceType === "mikrotik" ? MIKROTIK_DEFAULTS : deviceType === "nas" ? NAS_DEFAULTS : metricNames;
  return preferred.filter((metric) => metricNames.includes(metric) && !metric.startsWith("interface:") && !metric.startsWith("queue:") && !metric.startsWith("firewall:"));
}

export function numericSamplesByMetric(samples: readonly MetricSample[], windowHours: number) {
  const latest = samples.reduce((timestamp, sample) => Math.max(timestamp, new Date(sample.checked_at).getTime()), 0);
  const cutoff = latest - windowHours * 60 * 60 * 1000;
  const groups = new Map<string, MetricSample[]>();
  samples.filter((sample) => sample.metric_value_numeric !== null && new Date(sample.checked_at).getTime() >= cutoff).forEach((sample) => {
    groups.set(sample.metric_name, [...(groups.get(sample.metric_name) ?? []), sample]);
  });
  return [...groups.entries()]
    .map(([metricName, values]) => [metricName, values.sort((left, right) => left.checked_at.localeCompare(right.checked_at))] as const)
    .sort(([left], [right]) => left.localeCompare(right));
}

export function metricSummary(samples: readonly MetricSample[]) {
  const ordered = [...samples].sort((left, right) => left.checked_at.localeCompare(right.checked_at));
  const values = ordered.map((sample) => sample.metric_value_numeric).filter((value): value is number => value !== null);
  const latest = ordered.at(-1);
  const previous = values.at(-2);
  const current = values.at(-1);
  return { latest, average: values.reduce((sum, value) => sum + value, 0) / (values.length || 1), min: Math.min(...values), max: Math.max(...values), delta: current !== undefined && previous !== undefined ? current - previous : undefined };
}
