"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch, withQuery } from "@/lib/api/client";
import type { LiveMonitoringContext } from "./types";

export type GroupMonitoringFilters = {
  group: "voip" | "ruijie";
  mode: "live" | "range";
  metric: string;
  status: string;
  from: string;
  to: string;
  deviceOffset: number;
  snapshotOffset: number;
};

export function useGroupMonitoring(filters: GroupMonitoringFilters, enabled: boolean) {
  return useQuery({
    queryKey: ["live-monitoring-group", filters],
    queryFn: ({ signal }) => apiFetch<LiveMonitoringContext>(withQuery("/metrics/history/group", {
      group: filters.group,
      mode: filters.mode,
      metric_name: filters.metric,
      status: filters.status,
      device_limit: 20,
      device_offset: filters.deviceOffset,
      snapshot_limit: 10,
      snapshot_offset: filters.snapshotOffset,
      checked_from: filters.mode === "range" ? `${filters.from}T00:00:00+07:00` : undefined,
      checked_to: filters.mode === "range" ? `${filters.to}T23:59:59+07:00` : undefined
    }), { signal }),
    enabled,
    refetchInterval: filters.mode === "live" ? 15_000 : false
  });
}
