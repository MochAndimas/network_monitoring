"use client";

import { useQuery } from "@tanstack/react-query";
import { PlotlyChart, statusChartColor } from "@/components/charts/plotly-chart";
import { DataTable } from "@/components/ui/data-table";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { apiFetch } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";

const SEVERITY_ORDER = ["critical", "high", "warning", "low"];

export function ActiveAlertDistribution({ counts }: { counts: Record<string, number> }) {
  const rows = Object.entries(counts).filter(([, count]) => count > 0).sort(([left], [right]) => {
    const rank = (severity: string) => {
      const index = SEVERITY_ORDER.indexOf(severity);
      return index < 0 ? SEVERITY_ORDER.length : index;
    };
    return rank(left) - rank(right) || left.localeCompare(right);
  });
  const total = rows.reduce((sum, [, count]) => sum + count, 0);

  return <section className="insight-distribution">
    <h3>Distribusi Alert Aktif</h3>
    {total > 0 ? <PlotlyChart
      ariaLabel="Distribusi severity seluruh alert aktif"
      data={[{
        type: "bar", orientation: "h",
        x: rows.map(([, count]) => count), y: rows.map(([severity]) => severity),
        marker: { color: rows.map(([severity]) => statusChartColor(severity)) },
        hovertemplate: "%{y}: %{x} alert<extra></extra>"
      }]}
      layout={{ xaxis: { title: { text: "Jumlah alert" }, dtick: total <= 10 ? 1 : undefined }, yaxis: { autorange: "reversed", automargin: true } }}
    /> : <p>Tidak ada alert aktif dalam cakupan ini.</p>}
    <DataTable
      columns={[
        { key: "severity", label: "Severity", render: ([severity]) => <StatusBadge value={severity} /> },
        { key: "count", label: "Jumlah alert", render: ([, count]) => count }
      ]}
      rows={rows} pageSize={null} emptyLabel="Tidak ada alert aktif."
    />
  </section>;
}

export function LiveActiveAlertSummary() {
  const query = useQuery({
    queryKey: ["alerts", "active-summary"],
    queryFn: ({ signal }) => apiFetch<Record<string, number>>("/alerts/active/summary", { signal }),
    refetchInterval: 15_000
  });

  return <section>
    {query.isPending ? <LoadingState label="Memuat ringkasan alert…" />
      : query.isError ? <ErrorState message="Ringkasan alert tidak dapat dimuat." onRetry={() => void query.refetch()} />
        : <>
          <ActiveAlertDistribution counts={query.data} />
          <p>Diperbarui: {formatWib(new Date(query.dataUpdatedAt).toISOString())} · refresh 15 detik</p>
        </>}
  </section>;
}
