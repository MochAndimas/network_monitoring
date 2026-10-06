import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api/client";
import { useGroupMonitoring, type GroupMonitoringFilters } from "./use-group-monitoring";

vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), apiFetch: vi.fn() }));
const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; vi.resetAllMocks(); });
const filters: GroupMonitoringFilters = { group: "voip", mode: "live", metric: "", status: "", from: "2026-10-01", to: "2026-10-01", deviceOffset: 0, snapshotOffset: 0 };
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return function Wrapper({ children }: { children: React.ReactNode }) { return <QueryClientProvider client={client}>{children}</QueryClientProvider>; };
}

it("uses one aggregate request regardless of group size and refetches once", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ group: { total_devices: 100 } });
  const { result } = renderHook(() => useGroupMonitoring(filters, true), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(apiFetch).toHaveBeenCalledTimes(1);
  expect(vi.mocked(apiFetch).mock.calls[0][0]).toContain("/metrics/history/group?group=voip");
  await act(async () => { await result.current.refetch(); });
  expect(apiFetch).toHaveBeenCalledTimes(2);
});

it("aborts obsolete requests when filters change and when the group is disabled", async () => {
  const signals: AbortSignal[] = [];
  vi.mocked(apiFetch).mockImplementation((_path, options) => {
    signals.push(options?.signal as AbortSignal);
    return new Promise(() => undefined);
  });
  const { rerender, unmount } = renderHook(({ selected }) => useGroupMonitoring(selected, true), { initialProps: { selected: filters }, wrapper: wrapper() });
  await waitFor(() => expect(signals).toHaveLength(1));
  rerender({ selected: { ...filters, metric: "ping" } });
  await waitFor(() => expect(signals).toHaveLength(2));
  expect(signals[0].aborted).toBe(true);
  unmount();
  expect(signals[1].aborted).toBe(true);
});

it("does not fetch while disabled and passes explicit WIB range bounds", async () => {
  vi.mocked(apiFetch).mockResolvedValue({});
  const { rerender } = renderHook(({ enabled }) => useGroupMonitoring({ ...filters, mode: "range" }, enabled), { initialProps: { enabled: false }, wrapper: wrapper() });
  expect(apiFetch).not.toHaveBeenCalled();
  rerender({ enabled: true });
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
  const url = new URL(vi.mocked(apiFetch).mock.calls[0][0], "http://fixture");
  expect(url.searchParams.get("checked_from")).toBe("2026-10-01T00:00:00+07:00");
  expect(url.searchParams.get("checked_to")).toBe("2026-10-01T23:59:59+07:00");
});
