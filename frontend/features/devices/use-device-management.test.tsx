import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { useDeviceManagement } from "./use-device-management";
import type { DeviceDraft } from "./types";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  apiFetch: mocks.apiFetch,
}));
const filters = {
  debouncedSearch: "",
  type: "",
  status: "",
  activeOnly: false,
  offset: 0,
};
const draft: DeviceDraft = {
  name: "Fixture",
  ip_address: "192.0.2.1",
  device_type: "switch",
  site: null,
  location: null,
  description: null,
  is_active: true,
};
function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}
beforeEach(() => {
  mocks.apiFetch.mockReset().mockImplementation((url, options) => {
    if (options?.method) return Promise.resolve({ id: 1, ...draft });
    if (url.includes("/devices/paged"))
      return Promise.resolve({
        items: [],
        meta: { total: 0, limit: 10, offset: 0, has_more: false },
      });
    return Promise.resolve(url.includes("meta/types") ? [] : {});
  });
});
test("save uses create endpoint, invalidates inventory and closes the form", async () => {
  const { result } = renderHook(() => useDeviceManagement(filters), {
    wrapper: wrapper(),
  });
  await waitFor(() => expect(result.current.devices.isSuccess).toBe(true));
  act(() => result.current.setEditing("new"));
  await act(async () => {
    await result.current.saveDevice(draft);
  });
  expect(mocks.apiFetch).toHaveBeenCalledWith(
    "/devices",
    expect.objectContaining({ method: "POST", body: JSON.stringify(draft) }),
  );
  expect(result.current.editing).toBeNull();
});
test("changing a filter aborts the previous inventory fetch", async () => {
  const signals: AbortSignal[] = [];
  mocks.apiFetch.mockImplementation((url, options) => {
    if (url.includes("limit=10")) {
      signals.push(options.signal);
      return new Promise(() => {});
    }
    return Promise.resolve(url.includes("paged") ? { items: [] } : []);
  });
  const { rerender, unmount } = renderHook(
    ({ search }) =>
      useDeviceManagement({ ...filters, debouncedSearch: search }),
    { initialProps: { search: "first" }, wrapper: wrapper() },
  );
  await waitFor(() => expect(signals).toHaveLength(1));
  rerender({ search: "second" });
  await waitFor(() => expect(signals).toHaveLength(2));
  expect(signals[0].aborted).toBe(true);
  expect(signals[1].aborted).toBe(false);
  unmount();
  expect(signals[1].aborted).toBe(true);
});
