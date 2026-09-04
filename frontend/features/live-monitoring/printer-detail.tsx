import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import type { MetricSample } from "./types";

function latestByMetric(samples: MetricSample[]) {
  return new Map(samples.slice().sort((left, right) => right.checked_at.localeCompare(left.checked_at)).map((item) => [item.metric_name, item]));
}

function duration(seconds: number | null | undefined) {
  if (seconds == null) return "-";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  return `${days ? `${days}h ` : ""}${hours}j ${minutes}m`;
}

function humanize(value: string | undefined) {
  return value ? value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "-";
}

function printerStatusLabel(value: string | undefined) {
  if (value === "other") return "Tidak dirinci";
  if (value === "unknown") return "Tidak diketahui";
  return humanize(value);
}

export function PrinterDetail({ samples }: { samples: MetricSample[] }) {
  const latest = latestByMetric(samples);
  const collector = latest.get("printer_snmp_collection_status");
  const paperDetail = latest.get("printer_paper_detail")?.metric_value;
  const totalPages = latest.get("printer_total_pages")?.metric_value_numeric;
  const tonerCards = [
    ["Black", "printer_toner_black_percent"],
    ["Cyan", "printer_toner_cyan_percent"],
    ["Magenta", "printer_toner_magenta_percent"],
    ["Yellow", "printer_toner_yellow_percent"],
  ].filter(([, metricName]) => latest.has(metricName));
  const hasColorToners = tonerCards.length > 1;

  return <section>
    <h2>Kesehatan Printer</h2>
    {collector && collector.metric_value.toLowerCase() !== "ok" ? <p className="form-error">Data SNMP belum dapat dikumpulkan ({collector.metric_value}, {(collector.unit || "SNMP").toUpperCase()}). Status kertas, toner, dan counter mungkin stale.</p> : null}
    <MetricGrid columns={4}>
      <MetricCard label="Kolektor SNMP" value={collector?.metric_value ?? "-"} />
      <MetricCard label="Status Keseluruhan" value={printerStatusLabel(latest.get("printer_status")?.metric_value)} />
      <MetricCard label="Status Error" value={humanize(latest.get("printer_error_state")?.metric_value)} />
      <MetricCard label="Status Kertas" value={paperDetail ? `${humanize(latest.get("printer_paper_status")?.metric_value)} · ${humanize(paperDetail)}` : humanize(latest.get("printer_paper_status")?.metric_value)} />
    </MetricGrid>
    <MetricGrid columns={hasColorToners ? 3 : 4}>
      <MetricCard label="Status Tinta" value={humanize(latest.get("printer_ink_status")?.metric_value)} />
      <MetricCard label="Uptime" value={duration(latest.get("printer_uptime_seconds")?.metric_value_numeric)} />
      <MetricCard label="Total Halaman" value={totalPages == null ? "-" : `${totalPages.toLocaleString("id-ID")} pages`} />
      {!hasColorToners ? tonerCards.map(([label, metricName]) => {
        const toner = latest.get(metricName);
        return <MetricCard key={metricName} label={`Toner ${label}`} value={toner?.metric_value_numeric == null ? "-" : `${toner.metric_value_numeric}%`} />;
      }) : null}
    </MetricGrid>
    {hasColorToners ? <MetricGrid columns={4}>
      {tonerCards.map(([label, metricName]) => {
        const toner = latest.get(metricName);
        return <MetricCard key={metricName} label={`Toner ${label}`} value={toner?.metric_value_numeric == null ? "-" : `${toner.metric_value_numeric}%`} />;
      })}
    </MetricGrid> : null}
  </section>;
}
