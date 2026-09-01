import { PlotlyChart } from "@/components/charts/plotly-chart";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatWib } from "@/lib/formatters";
import type { MetricSample } from "./types";
import { metricLabel, metricSummary, numericSamplesByMetric } from "./trend-utils";

function displayNumber(value: number, unit: string | null | undefined) {
  return `${new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(value)}${unit ? ` ${unit}` : ""}`;
}

export function LiveTrends({ deviceName, selectedMetric, samples, windowHours }: { deviceName?: string; selectedMetric: string; samples: MetricSample[]; windowHours: number }) {
  if (!deviceName) return <section><h2>Tren Metrik</h2><p>Pilih satu device untuk menampilkan grafik tren.</p></section>;
  const groups = numericSamplesByMetric(samples, windowHours);
  const selectedSamples = selectedMetric ? groups.find(([name]) => name === selectedMetric)?.[1] ?? [] : [];
  const summary = selectedSamples.length ? metricSummary(selectedSamples) : undefined;

  return <section>
    <h2>Tren Metrik</h2>
    {summary?.latest ? <><h3>Ringkasan Metrik Terpilih</h3><MetricGrid columns={6}>
      <MetricCard label="Nilai terakhir" value={displayNumber(summary.latest.metric_value_numeric ?? 0, summary.latest.unit)} />
      <MetricCard label="Arah tren" value={summary.delta === undefined ? "Stabil (data awal)" : summary.delta === 0 ? "Stabil (0)" : `${summary.delta > 0 ? "Naik" : "Turun"} ${displayNumber(Math.abs(summary.delta), summary.latest.unit)}`} />
      <MetricCard label="Rata-rata" value={displayNumber(summary.average, summary.latest.unit)} />
      <MetricCard label="Minimum" value={displayNumber(summary.min, summary.latest.unit)} />
      <MetricCard label="Maksimum" value={displayNumber(summary.max, summary.latest.unit)} />
      <MetricCard label="Status terakhir" value={<StatusBadge value={summary.latest.status} />} />
    </MetricGrid></> : null}
    {groups.length ? groups.map(([metricName, values]) => {
      const latest = values.at(-1);
      return <section key={metricName}>
        <h3>{metricLabel(metricName)} - {deviceName}</h3>
        <p>{values.length} sampel · terakhir {formatWib(latest?.checked_at)}</p>
        <PlotlyChart ariaLabel={`Tren ${metricLabel(metricName)} untuk ${deviceName}`} data={[{ type: "scatter", mode: "lines+markers", x: values.map((item) => item.checked_at), y: values.map((item) => item.metric_value_numeric), hovertemplate: "%{x}<br>%{y}<extra></extra>" }]} layout={{ xaxis: { title: { text: "Waktu Check (WIB)" } }, yaxis: { title: { text: `${metricLabel(metricName)}${latest?.unit ? ` (${latest.unit})` : ""}` } }, showlegend: false }} />
      </section>;
    }) : <p>Belum ada data numerik untuk kombinasi device dan metrik ini.</p>}
  </section>;
}
