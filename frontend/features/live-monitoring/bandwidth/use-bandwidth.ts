import { useQuery } from "@tanstack/react-query";
import { apiFetch, withQuery } from "@/lib/api/client";
import { rangeError, wibToday } from "./format";
import type { ClientPage, ReportRange, UsagePage } from "./types";

export const BANDWIDTH_PAGE_SIZE = 10;

export function useDailyUsage(
  routerId: number,
  range: ReportRange,
  clientId?: number,
) {
  const valid = !rangeError(range);
  const today = wibToday();
  return useQuery({
    queryKey: ["bandwidth", routerId, "daily", range, clientId],
    queryFn: ({ signal }) =>
      apiFetch<UsagePage>(
        withQuery(`/bandwidth/${routerId}/usage/daily`, {
          ...range,
          client_id: clientId,
        }),
        { signal },
      ),
    enabled: valid,
    staleTime: 30_000,
    refetchInterval:
      valid && range.start <= today && range.end >= today ? 60_000 : false,
    retry: 1,
  });
}

export function useBandwidth(
  routerId: number,
  range: ReportRange,
  clientId: number | undefined,
  offset: number,
  afterId: number,
) {
  const valid = !rangeError(range);
  const today = wibToday();
  const base = `/bandwidth/${routerId}`;
  const reportOptions = {
    enabled: valid,
    staleTime: 30_000,
    refetchInterval:
      valid && range.start <= today && range.end >= today
        ? 60_000
        : (false as const),
    retry: 1,
  };
  const daily = useDailyUsage(routerId, range, clientId);
  const top = useQuery({
    queryKey: ["bandwidth", routerId, "top", range, offset],
    queryFn: ({ signal }) =>
      apiFetch<UsagePage>(
        withQuery(`${base}/usage/top`, {
          ...range,
          limit: BANDWIDTH_PAGE_SIZE,
          offset,
        }),
        { signal },
      ),
    ...reportOptions,
  });
  const clients = useQuery({
    queryKey: ["bandwidth", routerId, "clients", afterId],
    queryFn: ({ signal }) =>
      apiFetch<ClientPage>(
        withQuery(`${base}/clients`, {
          limit: BANDWIDTH_PAGE_SIZE,
          after_id: afterId,
        }),
        { signal },
      ),
    staleTime: 30_000,
    retry: 1,
  });
  return { daily, top, clients };
}
