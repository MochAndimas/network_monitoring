import { PlotlyChart } from "@/components/charts/plotly-chart";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import type { MetricSample } from "./types";
import { metricLabel, numericSamplesByMetric } from "./trend-utils";

function format(value: number, unit: string | null | undefined) {
  return `${new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(value)}${unit ? ` ${unit}` : ""}`;
}

export function DeviceGroupDetail({ samples, selectedMetric, windowHours, label }: { samples: MetricSample[]; selectedMetric: string; windowHours: number; label: string }) {
  const groups = numericSamplesByMetric(samples, windowHours).filter(([name]) => !selectedMetric || name === selectedMetric);
  return <section>
    <h2>Tren Semua {label}</h2>
    <p>Setiap warna pada grafik mewakili satu device {label}; kartu memakai agregasi nilai terbaru antar-device.</p>
    {groups.length ? groups.map(([metricName, values]) => {
      const byDevice = new Map<string, MetricSample[]>();
      values.forEach((sample) => byDevice.set(sample.device_name, [...(byDevice.get(sample.device_name) ?? []), sample]));
      const latest = [...byDevice.values()].map((deviceSamples) => deviceSamples.at(-1)).filter((sample): sample is MetricSample => Boolean(sample));
      const current = latest.map((sample) => sample.metric_value_numeric).filter((value): value is number => value !== null);
      const unit = latest[0]?.unit;
      return <section key={metricName}>
        <h3>{metricLabel(metricName)} - Semua {label}</h3>
        <MetricGrid columns={4}>
          <MetricCard label="Rata-rata terkini" value={format(current.reduce((sum, value) => sum + value, 0) / (current.length || 1), unit)} />
          <MetricCard label="Minimum" value={format(Math.min(...current), unit)} />
          <MetricCard label="Maksimum" value={format(Math.max(...current), unit)} />
          <MetricCard label="Device dengan data" value={latest.length.toLocaleString("id-ID")} />
        </MetricGrid>
        <PlotlyChart ariaLabel={`Tren ${metricLabel(metricName)} untuk semua ${label}`} data={[...byDevice.entries()].map(([device, deviceSamples]) => ({ type: "scatter" as const, mode: "lines+markers" as const, name: device, x: deviceSamples.map((sample) => sample.checked_at), y: deviceSamples.map((sample) => sample.metric_value_numeric), hovertemplate: "%{x}<br>%{y}<extra>" + device + "</extra>" }))} layout={{ xaxis: { title: { text: "Waktu Check (WIB)" } }, yaxis: { title: { text: `${metricLabel(metricName)}${unit ? ` (${unit})` : ""}` } }, showlegend: true }} />
      </section>;
    }) : <p>Belum ada data {label} numerik untuk filter ini.</p>}
  </section>;
}
