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

export function PrinterDetail({ samples }: { samples: MetricSample[] }) {
  const latest = latestByMetric(samples);
  const collector = latest.get("printer_snmp_collection_status");
  const paperDetail = latest.get("printer_paper_detail")?.metric_value;
  const tonerBlack = latest.get("printer_toner_black_percent")?.metric_value_numeric;
  const totalPages = latest.get("printer_total_pages")?.metric_value_numeric;

  return <section>
    <h2>Kesehatan Printer</h2>
    {collector && collector.metric_value.toLowerCase() !== "ok" ? <p className="form-error">Data SNMP belum dapat dikumpulkan ({collector.metric_value}, {(collector.unit || "SNMP").toUpperCase()}). Status kertas, toner, dan counter mungkin stale.</p> : null}
    <MetricGrid columns={4}>
      <MetricCard label="Kolektor SNMP" value={collector?.metric_value ?? "-"} />
      <MetricCard label="Status Keseluruhan" value={humanize(latest.get("printer_status")?.metric_value)} />
      <MetricCard label="Status Error" value={humanize(latest.get("printer_error_state")?.metric_value)} />
      <MetricCard label="Status Kertas" value={paperDetail ? `${humanize(latest.get("printer_paper_status")?.metric_value)} · ${humanize(paperDetail)}` : humanize(latest.get("printer_paper_status")?.metric_value)} />
    </MetricGrid>
    <MetricGrid columns={4}>
      <MetricCard label="Status Tinta" value={humanize(latest.get("printer_ink_status")?.metric_value)} />
      <MetricCard label="Toner Black" value={tonerBlack == null ? "-" : `${tonerBlack}%`} />
      <MetricCard label="Uptime" value={duration(latest.get("printer_uptime_seconds")?.metric_value_numeric)} />
      <MetricCard label="Total Halaman" value={totalPages == null ? "-" : `${totalPages.toLocaleString("id-ID")} pages`} />
    </MetricGrid>
  </section>;
}
