"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { apiFetch } from "@/lib/api/client";
import { useUrlQuerySync } from "@/lib/use-url-query-sync";
import type { DeviceOption } from "../types";
import { BandwidthPanel } from "./bandwidth-panel";

function RouterPrompt({ deviceId }: { deviceId: string }) {
  const params = useSearchParams();
  // Preserve a report deep link while router options are loading or unavailable.
  useUrlQuerySync({
    tab: "bandwidth",
    device: deviceId,
    bw_from: params.get("bw_from"),
    bw_to: params.get("bw_to"),
    bw_client: params.get("bw_client"),
  });
  return (
    <p className="page-state">
      Pilih router MikroTik untuk melihat penggunaan bandwidth per perangkat.
    </p>
  );
}

export function BandwidthWorkspace({
  deviceId,
  onDeviceChange,
  tabs,
}: {
  deviceId: string;
  onDeviceChange: (value: string) => void;
  tabs: ReactNode;
}) {
  const devices = useQuery({
    queryKey: ["devices", "options"],
    queryFn: ({ signal }) =>
      apiFetch<DeviceOption[]>("/devices/options?active_only=true", { signal }),
  });
  // Match the API's router type, rather than guessing from a device name.
  const routers =
    devices.data?.filter(
      (item) => item.device_type.toLowerCase() === "mikrotik",
    ) ?? [];
  const selected = routers.find((item) => String(item.id) === deviceId);
  return (
    <main className="app-page live-monitoring-page">
      <PageHeader
        className="live-monitoring-header"
        title="Live Monitoring"
        description="Penggunaan internet tercatat per perangkat dari flow MikroTik, dengan laporan harian WIB."
      />
      {tabs}
      <div
        id="monitoring-bandwidth-panel"
        role="tabpanel"
        aria-labelledby="monitoring-bandwidth-tab"
      >
        <div className="filter-panel">
          <label>
            Router MikroTik
            <select
              value={selected ? deviceId : ""}
              onChange={(event) => onDeviceChange(event.target.value)}
            >
              <option value="">Pilih router MikroTik</option>
              {routers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.ip_address}
                </option>
              ))}
            </select>
          </label>
        </div>
        {devices.isPending ? <LoadingState label="Memuat router…" /> : null}
        {devices.isError ? (
          <ErrorState
            message="Daftar router tidak dapat dimuat."
            onRetry={() => {
              void devices.refetch();
            }}
          />
        ) : null}
        {!devices.isPending && !devices.isError && selected ? (
          <BandwidthPanel key={selected.id} routerId={selected.id} />
        ) : (
          <RouterPrompt deviceId={deviceId} />
        )}
      </div>
    </main>
  );
}
