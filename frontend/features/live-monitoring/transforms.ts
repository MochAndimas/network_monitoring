export type NumericMetricSample = { device_name: string; metric_name: string; metric_value_numeric: number | null; checked_at: string; unit: string | null };

export function toNumericTrendSeries(items: readonly NumericMetricSample[], metricName?: string) {
  const selected = items.filter((item) => item.metric_value_numeric !== null && (!metricName || item.metric_name === metricName));
  const groups = new Map<string, NumericMetricSample[]>();
  selected.forEach((item) => groups.set(item.device_name, [...(groups.get(item.device_name) ?? []), item]));
  return [...groups.entries()].map(([device, samples]) => ({ name: device, type: "scatter" as const, mode: "lines+markers" as const, x: samples.map((sample) => sample.checked_at), y: samples.map((sample) => sample.metric_value_numeric), hovertemplate: "%{x}<br>%{y}<extra>" + device + "</extra>" }));
}
