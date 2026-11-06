"use client";

import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { formatEpochNs, rangeError, summarizeUsage } from "./format";
import { ByteValue, DailyTable } from "./usage-tables";
import { useDailyUsage } from "./use-bandwidth";
import type { ReportRange } from "./types";

export function DailyUsageReport({
  routerId,
  range,
  clientId,
  name = "Semua perangkat",
}: {
  routerId: number;
  range: ReportRange;
  clientId?: number;
  name?: string;
}) {
  const daily = useDailyUsage(routerId, range, clientId);
  const totals = daily.data ? summarizeUsage(daily.data.items) : undefined;
  const valid = !rangeError(range);
  const titleId =
    clientId === undefined
      ? "bandwidth-daily-title"
      : "bandwidth-client-daily-title";
  return (
    <section className="live-monitoring-data-section" aria-labelledby={titleId}>
      <div className="section-header">
        <h2 id={titleId}>Penggunaan harian · {name}</h2>
      </div>
      {valid && daily.isPending ? (
        <LoadingState label="Memuat penggunaan harian…" />
      ) : null}
      {daily.isError ? (
        <ErrorState
          message="Penggunaan harian tidak dapat dimuat. Periksa periode atau tutup detail jika perangkat tidak ditemukan."
          onRetry={() => {
            void daily.refetch();
          }}
        />
      ) : null}
      {valid && daily.data && totals ? (
        <>
          <p className="bandwidth-updated" aria-live="polite">
            {daily.isFetching ? "Memperbarui… · " : ""}Data tercatat terakhir
            diperbarui:{" "}
            {totals.updated > 0n
              ? `${formatEpochNs(String(totals.updated))} WIB`
              : "belum ada data"}
            . Waktu ini tidak menunjukkan collector aktif.
          </p>
          {daily.data.items.length ? (
            <MetricGrid columns={5}>
              <MetricCard
                label="Upload tercatat"
                value={<ByteValue value={String(totals.upload)} />}
              />
              <MetricCard
                label="Download tercatat"
                value={<ByteValue value={String(totals.download)} />}
              />
              <MetricCard
                label="Total tercatat"
                value={<ByteValue value={String(totals.total)} />}
              />
              <MetricCard
                label="Alokasi lintas hari (estimasi)"
                value={<ByteValue value={String(totals.estimated)} />}
              />
              <MetricCard
                label="Identitas belum terpetakan"
                value={<ByteValue value={String(totals.unresolved)} />}
              />
            </MetricGrid>
          ) : null}
          {daily.isError ? (
            <p className="bandwidth-help">
              Menampilkan data terakhir yang berhasil dimuat.
            </p>
          ) : null}
          <DailyTable rows={daily.data.items} />
          <p className="bandwidth-help">
            Hari tanpa baris belum membuktikan penggunaan nol. Arahkan pointer
            ke angka untuk melihat jumlah byte utuh.
          </p>
        </>
      ) : null}
    </section>
  );
}
