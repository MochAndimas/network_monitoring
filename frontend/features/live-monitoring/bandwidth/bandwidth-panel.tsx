"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { CursorPagination } from "@/components/ui/cursor-pagination";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { useUrlQuerySync } from "@/lib/use-url-query-sync";
import { rangeError, wibToday } from "./format";
import { ClientsTable, TopTable } from "./usage-tables";
import { BANDWIDTH_PAGE_SIZE, useBandwidth } from "./use-bandwidth";

import { DailyUsageReport } from "./daily-usage-report";
import { ClientUsageDialog } from "./client-usage-dialog";

/** Remount per router so identities and pagination never leak across routers. */
export function BandwidthPanel({ routerId }: { routerId: number }) {
  const params = useSearchParams();
  const [range, setRange] = useState(() => ({
    start: params.get("bw_from") ?? wibToday(),
    end: params.get("bw_to") ?? wibToday(),
  }));
  const [draft, setDraft] = useState(range);
  const [validation, setValidation] = useState(() => rangeError(range));
  const [selection, setSelection] = useState<
    { id: number; name: string } | undefined
  >(() => {
    const id =
      params.get("device") === String(routerId)
        ? Number(params.get("bw_client"))
        : NaN;
    return Number.isSafeInteger(id) && id > 0
      ? { id, name: `Klien #${id}` }
      : undefined;
  });
  const [topOffset, setTopOffset] = useState(0);
  const [clientTrail, setClientTrail] = useState([0]);
  const afterId = clientTrail[clientTrail.length - 1];
  const { daily, top, clients } = useBandwidth(
    routerId,
    range,
    undefined,
    topOffset,
    afterId,
  );
  useUrlQuerySync({
    tab: "bandwidth",
    device: routerId,
    bw_from: range.start,
    bw_to: range.end,
    bw_client: selection?.id,
  });
  const valid = !rangeError(range);
  function selectClient(id: number, name: string) {
    setSelection({ id, name });
  }

  return (
    <div className="bandwidth-panel">
      <form
        className="filter-panel bandwidth-filters"
        onSubmit={(event) => {
          event.preventDefault();
          const error = rangeError(draft);
          setValidation(error);
          if (!error) {
            setRange({ ...draft });
            setTopOffset(0);
          }
        }}
      >
        <label>
          Tanggal mulai (WIB)
          <input
            type="date"
            value={draft.start}
            onChange={(event) =>
              setDraft({ ...draft, start: event.target.value })
            }
          />
        </label>
        <label>
          Tanggal akhir (WIB)
          <input
            type="date"
            value={draft.end}
            onChange={(event) =>
              setDraft({ ...draft, end: event.target.value })
            }
          />
        </label>
        <button type="submit">Terapkan periode</button>
        <button
          className="button-secondary"
          type="button"
          disabled={daily.isFetching || top.isFetching || clients.isFetching}
          onClick={() => {
            if (valid) {
              void daily.refetch();
              void top.refetch();
            }
            void clients.refetch();
          }}
        >
          Perbarui data
        </button>
      </form>
      {validation ? (
        <p className="bandwidth-validation" role="alert">
          {validation}
        </p>
      ) : null}
      <aside className="bandwidth-quality" aria-label="Kualitas data bandwidth">
        <strong>Kelengkapan traffic belum terverifikasi</strong>
        <p>
          Flow IPFIX bisa terlambat masuk, hilang, atau terduplikasi. Pembagian
          flow lintas hari merupakan estimasi proporsional. Angka ini adalah
          penggunaan tercatat, bukan kecepatan internet saat ini.
        </p>
        <p>
          Periode laporan: {range.start} s.d. {range.end} (WIB), maksimal 31
          hari. Periode hari ini diperbarui otomatis setiap 60 detik.
        </p>
      </aside>

      <DailyUsageReport routerId={routerId} range={range} />
      {selection && (
        <ClientUsageDialog
          routerId={routerId}
          range={range}
          clientId={selection.id}
          name={
            selection.name === `Klien #${selection.id}`
              ? (clients.data?.items.find((item) => item.id === selection.id)
                  ?.display_name ??
                top.data?.items.find((item) => item.client_id === selection.id)
                  ?.display_name ??
                selection.name)
              : selection.name
          }
          onClose={() => setSelection(undefined)}
        />
      )}

      <section
        className="live-monitoring-data-section"
        aria-labelledby="bandwidth-top-title"
      >
        <div className="section-header">
          <h2 id="bandwidth-top-title">Top pengguna · Semua perangkat</h2>
        </div>
        <p className="bandwidth-help">
          Peringkat untuk seluruh periode laporan. Klik nama perangkat untuk
          membuka detail penggunaan hariannya.
        </p>
        {valid && top.isPending ? (
          <LoadingState label="Memuat top pengguna…" />
        ) : null}
        {top.isError ? (
          <ErrorState
            message="Top pengguna tidak dapat dimuat."
            onRetry={() => {
              void top.refetch();
            }}
          />
        ) : null}
        {valid && top.data ? (
          <>
            <TopTable rows={top.data.items} onSelect={selectClient} />
            <CursorPagination
              itemCount={top.data.items.length}
              limit={BANDWIDTH_PAGE_SIZE}
              total={null}
              pageIndex={topOffset / BANDWIDTH_PAGE_SIZE}
              hasNext={
                top.data.has_more && topOffset + BANDWIDTH_PAGE_SIZE <= 10000
              }
              hasPrevious={topOffset > 0}
              onNext={() =>
                setTopOffset((value) => value + BANDWIDTH_PAGE_SIZE)
              }
              onPrevious={() =>
                setTopOffset((value) =>
                  Math.max(0, value - BANDWIDTH_PAGE_SIZE),
                )
              }
            />
            {topOffset + BANDWIDTH_PAGE_SIZE > 10000 && top.data.has_more ? (
              <p className="bandwidth-help">
                Batas halaman tercapai. Persempit periode laporan.
              </p>
            ) : null}
          </>
        ) : null}
      </section>

      <section
        className="live-monitoring-data-section"
        aria-labelledby="bandwidth-clients-title"
      >
        <div className="section-header">
          <h2 id="bandwidth-clients-title">Inventaris perangkat</h2>
        </div>
        <p className="bandwidth-help">
          Hasil observasi DHCP/ARP. Terakhir diamati tidak membuktikan perangkat
          sedang online. Klik nama untuk melihat penggunaan.
        </p>
        {clients.isPending ? <LoadingState label="Memuat inventaris…" /> : null}
        {clients.isError ? (
          <ErrorState
            message="Inventaris perangkat tidak dapat dimuat."
            onRetry={() => {
              void clients.refetch();
            }}
          />
        ) : null}
        {clients.data ? (
          <>
            <ClientsTable rows={clients.data.items} onSelect={selectClient} />
            <CursorPagination
              itemCount={clients.data.items.length}
              limit={BANDWIDTH_PAGE_SIZE}
              total={null}
              pageIndex={clientTrail.length - 1}
              hasNext={clients.data.next_after_id !== null}
              hasPrevious={clientTrail.length > 1}
              onNext={() => {
                const next = clients.data.next_after_id;
                if (next !== null) setClientTrail((trail) => [...trail, next]);
              }}
              onPrevious={() =>
                setClientTrail((trail) =>
                  trail.length > 1 ? trail.slice(0, -1) : trail,
                )
              }
            />
          </>
        ) : null}
      </section>
    </div>
  );
}
