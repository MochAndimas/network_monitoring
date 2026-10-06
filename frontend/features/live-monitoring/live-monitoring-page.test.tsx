import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api/client";
import { LiveMonitoringPage } from "./live-monitoring-page";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("device=__voip__") }));
vi.mock("@/lib/use-url-query-sync", () => ({ initialOffset: () => 0, useUrlQuerySync: () => undefined }));
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), apiFetch: vi.fn() }));
vi.mock("@/components/charts/plotly-chart", () => ({ PlotlyChart: () => <div>Chart</div>, statusChartColor: () => "red" }));
let client: QueryClient;
afterEach(() => { client.clear(); vi.resetAllMocks(); });
const empty = { items: [], meta: { total: 0, limit: 10, offset: 0 } };
function groupPayload() {
  return { metric_names: ["ping"], history: empty, selected_device_trend: empty, selected_device_snapshot: empty,
    latest_snapshot: empty, latest_snapshot_status_summary: { unknown: 1 }, snapshot_uptime_map: {},
    group: { total_devices: 100, device_limit: 20, device_offset: 0, samples_per_series: 50,
      trend_sampled: false, value_char_limit: 256,
      devices: [{ id: 1, name: "VoIP 1", site: "A", status: "unknown", freshness: "no_data", latest_checked_at: null }] } };
}
function mount() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><LiveMonitoringPage /></QueryClientProvider>);
}
function mockDevices(path: string) {
  return path.startsWith("/devices/options") ? Array.from({ length: 100 }, (_, i) => ({ id: i + 1, name: `VoIP ${i}`, device_type: "voip", ip_address: `192.0.2.${i + 1}` })) : undefined;
}

it("renders group freshness, detail links and pagination without per-device or global history requests", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path) => mockDevices(path) ?? groupPayload());
  mount();
  expect(await screen.findByRole("heading", { name: "Perangkat dalam grup VoIP" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "VoIP 1" })).toHaveAttribute("href", "/live-monitoring?device=1");
  expect(screen.getByText("Belum ada data")).toBeInTheDocument();
  const requested = vi.mocked(apiFetch).mock.calls.map(([path]) => path);
  expect(requested).toHaveLength(2);
  expect(requested.filter((path) => path.startsWith("/metrics/history/group"))).toHaveLength(1);
  fireEvent.click(screen.getAllByRole("button", { name: "Berikutnya" })[0]);
  await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path]) => path.includes("device_offset=20"))).toBe(true));
  expect(vi.mocked(apiFetch).mock.calls.every(([path]) => path.startsWith("/devices/options") || path.startsWith("/metrics/history/group"))).toBe(true);
});

it("retries a failed group request without refetching disabled global queries", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    const devices = mockDevices(path);
    if (devices) return devices;
    throw new Error("fixture failure");
  });
  mount();
  expect(await screen.findByText("Live monitoring tidak dapat dimuat.")).toBeInTheDocument();
  vi.mocked(apiFetch).mockImplementation(async (path) => mockDevices(path) ?? groupPayload());
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("heading", { name: "Perangkat dalam grup VoIP" })).toBeInTheDocument();
  expect(vi.mocked(apiFetch).mock.calls.every(([path]) => path.startsWith("/devices/options") || path.startsWith("/metrics/history/group"))).toBe(true);
});
