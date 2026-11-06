import { DataTable, type TableColumn } from "@/components/ui/data-table";
import { exactBytes, formatBytes, formatEpochNs, barPercent } from "./format";
import type { BandwidthClient, UsageRow } from "./types";

export function ByteValue({ value }: { value: string }) {
  return (
    <span
      className="bandwidth-byte-value"
      title={exactBytes(value)}
      aria-label={exactBytes(value)}
    >
      {formatBytes(value)}
    </span>
  );
}

const byteColumns: TableColumn<UsageRow>[] = [
  {
    key: "upload",
    label: "Upload",
    render: (row) => <ByteValue value={row.upload_bytes} />,
  },
  {
    key: "download",
    label: "Download",
    render: (row) => <ByteValue value={row.download_bytes} />,
  },
  {
    key: "total",
    label: "Total",
    render: (row) => (
      <strong>
        <ByteValue value={row.total_bytes} />
      </strong>
    ),
  },
  {
    key: "estimated",
    label: "Alokasi estimasi",
    render: (row) => <ByteValue value={row.estimated_bytes} />,
  },
  {
    key: "unresolved",
    label: "Belum terpetakan",
    render: (row) => <ByteValue value={row.unresolved_bytes} />,
  },
];

export function DailyTable({ rows }: { rows: UsageRow[] }) {
  return (
    <DataTable
      columns={[
        {
          key: "day",
          label: "Tanggal (WIB)",
          render: (row: UsageRow) => row.day,
        },
        ...byteColumns,
      ]}
      rows={rows}
      emptyLabel="Belum ada penggunaan tercatat pada periode ini. Ini belum membuktikan penggunaan nol."
    />
  );
}

export function TopTable({
  rows,
  onSelect,
}: {
  rows: UsageRow[];
  onSelect: (id: number, name: string) => void;
}) {
  const maximum = rows[0]?.total_bytes ?? "0";
  return (
    <DataTable
      pageSize={null}
      columns={[
        {
          key: "name",
          label: "Perangkat / IP",
          render: (row: UsageRow) => (
            <div className="bandwidth-subject">
              {row.client_id !== null ? (
                <button
                  className="bandwidth-client-link"
                  onClick={() =>
                    onSelect(
                      row.client_id!,
                      row.display_name ?? `Klien #${row.client_id}`,
                    )
                  }
                >
                  {row.display_name}
                </button>
              ) : (
                <strong>{row.unresolved_ip}</strong>
              )}
              {row.client_id === null && row.latest_observation && (
                <small>
                  Terakhir teramati:{" "}
                  <strong>{row.latest_observation.display_name}</strong>
                  {row.latest_observation.display_name !==
                  row.latest_observation.mac_address
                    ? ` · ${row.latest_observation.mac_address}`
                    : ""}
                  {` · ${formatEpochNs(row.latest_observation.observed_ns)} WIB`}
                </small>
              )}
              <small>
                {row.client_id === null
                  ? "Pemilik trafik historis belum terverifikasi; IP dapat dipakai bergantian."
                  : "Lihat histori perangkat"}
              </small>
              <div className="bandwidth-bar" aria-hidden="true">
                <span
                  style={{ width: `${barPercent(row.total_bytes, maximum)}%` }}
                />
              </div>
            </div>
          ),
        },
        ...byteColumns,
      ]}
      rows={rows}
      emptyLabel="Belum ada penggunaan tercatat untuk periode ini."
    />
  );
}

export function ClientsTable({
  rows,
  onSelect,
}: {
  rows: BandwidthClient[];
  onSelect: (id: number, name: string) => void;
}) {
  return (
    <DataTable
      pageSize={null}
      columns={[
        {
          key: "name",
          label: "Perangkat",
          render: (row: BandwidthClient) => (
            <button
              className="bandwidth-client-link"
              onClick={() => onSelect(row.id, row.display_name)}
            >
              {row.display_name}
            </button>
          ),
        },
        {
          key: "mac",
          label: "MAC",
          render: (row: BandwidthClient) => row.mac_address,
        },
        {
          key: "hostname",
          label: "Hostname",
          render: (row: BandwidthClient) => row.hostname || "—",
        },
        {
          key: "seen",
          label: "Terakhir diamati (WIB)",
          render: (row: BandwidthClient) => formatEpochNs(row.last_seen_ns),
        },
      ]}
      rows={rows}
      emptyLabel="Belum ada inventaris klien untuk router ini."
    />
  );
}
