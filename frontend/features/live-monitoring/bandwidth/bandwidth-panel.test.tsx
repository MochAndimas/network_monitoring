import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api/client";
import { useUrlQuerySync } from "@/lib/use-url-query-sync";
import { LiveMonitoringPage } from "../live-monitoring-page";
import type { UsageRow } from "./types";

let search = "tab=bandwidth&device=1&bw_from=2026-10-14&bw_to=2026-10-15";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/lib/use-url-query-sync", () => ({
  initialOffset: () => 0,
  useUrlQuerySync: vi.fn(),
}));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  apiFetch: vi.fn(),
}));
vi.mock("@/components/charts/plotly-chart", () => ({
  PlotlyChart: () => <div>Chart</div>,
  statusChartColor: () => "red",
}));

const row: UsageRow = {
  day: "2026-10-15",
  subject: "c:10",
  client_id: 10,
  display_name: "Office Laptop",
  unresolved_ip: null,
  upload_bytes: "9007199254740993",
  download_bytes: "1",
  total_bytes: "9007199254740994",
  estimated_bytes: "100",
  unresolved_bytes: "0",
  updated_ns: "1791997200000000001",
};
const routers = [
  { id: 1, name: "Router A", device_type: "mikrotik", ip_address: "192.0.2.1" },
  { id: 2, name: "Router B", device_type: "mikrotik", ip_address: "192.0.2.2" },
  {
    id: 3,
    name: "MikroTik Server",
    device_type: "server",
    ip_address: "192.0.2.3",
  },
];
function response(path: string) {
  const url = new URL(path, "http://fixture");
  if (url.pathname === "/devices/options") return routers;
  if (url.pathname.endsWith("/clients"))
    return {
      items: [
        {
          id: url.searchParams.get("after_id") === "10" ? 11 : 10,
          display_name: "Inventory Laptop",
          mac_address: "02:00:00:00:00:01",
          hostname: "office",
          custom_name: null,
          first_seen_ns: "1",
          last_seen_ns: row.updated_ns,
        },
      ],
      next_after_id: url.searchParams.get("after_id") === "10" ? null : 10,
    };
  if (!url.pathname.startsWith("/bandwidth/"))
    throw new Error(`Unexpected metric request ${path}`);
  return {
    router_id: url.pathname.includes("/2/") ? 2 : 1,
    start: url.searchParams.get("start"),
    end: url.searchParams.get("end"),
    timezone: "Asia/Jakarta",
    allocation: "proportional_integer_v1",
    completeness: "unverified",
    items: [row],
    limit: 10,
    offset: Number(url.searchParams.get("offset") ?? 0),
    has_more:
      url.pathname.endsWith("/top") &&
      Number(url.searchParams.get("offset") ?? 0) === 0,
  };
}
let client: QueryClient;
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
  search = "tab=bandwidth&device=1&bw_from=2026-10-14&bw_to=2026-10-15";
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, retryDelay: 0, gcTime: 0 } },
  });
  vi.mocked(apiFetch).mockImplementation(async (path) => response(path));
});
afterEach(() => {
  client.clear();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});
function mount() {
  return render(
    <QueryClientProvider client={client}>
      <LiveMonitoringPage />
    </QueryClientProvider>,
  );
}
function paths() {
  return vi.mocked(apiFetch).mock.calls.map(([path]) => path);
}

it("loads bandwidth independently of health metrics, shows data quality and exact byte titles", async () => {
  mount();
  expect(
    await screen.findByRole("heading", {
      name: "Top pengguna · Semua perangkat",
    }),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: "Office Laptop" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Bandwidth" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.getByText("Kelengkapan traffic belum terverifikasi"),
  ).toBeInTheDocument();
  expect(
    screen.getAllByTitle("9.007.199.254.740.993 byte").length,
  ).toBeGreaterThan(0);
  expect(paths()).toHaveLength(4);
  expect(
    paths().every(
      (path) =>
        path.startsWith("/bandwidth/1/") || path.startsWith("/devices/options"),
    ),
  ).toBe(true);
});

it("filters client history while retaining all-router ranking, and resets identity when router changes", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Office Laptop" }));
  await waitFor(() =>
    expect(
      paths().some(
        (path) => path.includes("daily?") && path.includes("client_id=10"),
      ),
    ).toBe(true),
  );
  expect(
    paths()
      .filter((path) => path.includes("/top?"))
      .every((path) => !path.includes("client_id")),
  ).toBe(true);
  expect(
    screen.getByRole("dialog", { name: "Detail bandwidth · Office Laptop" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", {
      name: "Penggunaan harian · Semua perangkat",
    }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Router MikroTik"), {
    target: { value: "2" },
  });
  await waitFor(() =>
    expect(
      paths().some((path) => path.startsWith("/bandwidth/2/usage/daily")),
    ).toBe(true),
  );
  expect(
    paths()
      .filter((path) => path.startsWith("/bandwidth/2/"))
      .every((path) => !path.includes("client_id")),
  ).toBe(true);
  expect(
    screen.getByRole("heading", {
      name: "Penggunaan harian · Semua perangkat",
    }),
  ).toBeInTheDocument();
});

it("closes details with Escape, restores focus and leaves the overview unchanged", async () => {
  mount();
  const trigger = await screen.findByRole("button", { name: "Office Laptop" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", {
    name: "Detail bandwidth · Office Laptop",
  });
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent(dialog, new Event("cancel", { bubbles: false, cancelable: true }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).toBe("");
  expect(trigger).toHaveFocus();
  expect(
    screen.getByRole("heading", {
      name: "Penggunaan harian · Semua perangkat",
    }),
  ).toBeInTheDocument();
});

it("validates draft dates before fetching and applies an inclusive report range", async () => {
  mount();
  await screen.findByRole("button", { name: "Office Laptop" });
  const originalCount = paths().length;
  fireEvent.change(screen.getByLabelText("Tanggal mulai (WIB)"), {
    target: { value: "2026-09-01" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Terapkan periode" }));
  expect(screen.getByRole("alert")).toHaveTextContent("maksimal 31 hari");
  expect(paths()).toHaveLength(originalCount);
  fireEvent.change(screen.getByLabelText("Tanggal mulai (WIB)"), {
    target: { value: "2026-10-01" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Terapkan periode" }));
  await waitFor(() =>
    expect(paths().some((path) => path.includes("start=2026-10-01"))).toBe(
      true,
    ),
  );
  expect(vi.mocked(useUrlQuerySync)).toHaveBeenLastCalledWith(
    expect.objectContaining({
      tab: "bandwidth",
      bw_from: "2026-10-01",
      bw_to: "2026-10-15",
    }),
  );
});

it.each(["button", "backdrop"])(
  "closes the device popup using %s",
  async (method) => {
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Office Laptop" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Detail bandwidth · Office Laptop",
    });
    fireEvent.click(
      method === "button"
        ? within(dialog).getByRole("button", { name: "Tutup detail" })
        : dialog,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(vi.mocked(useUrlQuerySync)).toHaveBeenLastCalledWith(
      expect.objectContaining({ bw_client: undefined }),
    );
  },
);

it("uses bounded top and keyset inventory pagination", async () => {
  mount();
  await screen.findByRole("button", { name: "Office Laptop" });
  const top = screen.getByRole("region", {
    name: "Top pengguna · Semua perangkat",
  });
  fireEvent.click(within(top).getByRole("button", { name: "Berikutnya" }));
  await waitFor(() =>
    expect(paths().some((path) => path.includes("offset=10"))).toBe(true),
  );
  const inventory = screen.getByRole("region", {
    name: "Inventaris perangkat",
  });
  fireEvent.click(
    within(inventory).getByRole("button", { name: "Berikutnya" }),
  );
  await waitFor(() =>
    expect(paths().some((path) => path.includes("after_id=10"))).toBe(true),
  );
  expect(
    paths()
      .filter((path) => path.includes("/clients?"))
      .every((path) => path.includes("limit=10")),
  ).toBe(true);
});

it("does not request bandwidth for a non-router, even if its name contains MikroTik", async () => {
  search = "tab=bandwidth&device=3";
  mount();
  expect(
    await screen.findByText(
      "Pilih router MikroTik untuk melihat penggunaan bandwidth per perangkat.",
    ),
  ).toBeInTheDocument();
  expect(paths()).toEqual(["/devices/options?active_only=true"]);
  expect(
    screen.queryByRole("option", { name: /MikroTik Server/ }),
  ).not.toBeInTheDocument();
});

it("retains working sections and offers retry when the daily request fails", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    if (path.includes("/daily?")) throw new Error("fixture failure");
    return response(path);
  });
  mount();
  const error = await screen.findByRole("alert");
  expect(error).toHaveTextContent("Penggunaan harian tidak dapat dimuat");
  expect(
    screen.getByRole("button", { name: "Office Laptop" }),
  ).toBeInTheDocument();
  vi.mocked(apiFetch).mockImplementation(async (path) => response(path));
  fireEvent.click(within(error).getByRole("button", { name: "Coba lagi" }));
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
  expect(screen.getByText("Total tercatat")).toBeInTheDocument();
});

it("keeps tab navigation available when health metrics fail", async () => {
  search = "device=1";
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    if (path.startsWith("/devices/options")) return routers;
    if (path.startsWith("/metrics")) throw new Error("metrics unavailable");
    return response(path);
  });
  mount();
  const tab = screen.getByRole("tab", { name: "Metrik perangkat" });
  fireEvent.keyDown(tab, { key: "ArrowRight" });
  await screen.findByRole("button", { name: "Office Laptop" });
  expect(screen.getByRole("tab", { name: "Bandwidth" })).toHaveFocus();
});

it("does not present missing daily observations as zero usage", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path) =>
    path.includes("/daily?")
      ? { ...response(path), items: [] }
      : response(path),
  );
  mount();
  expect(
    await screen.findByText(/Belum ada penggunaan tercatat pada periode ini/),
  ).toBeInTheDocument();
  expect(screen.queryByText("Total tercatat")).not.toBeInTheDocument();
  expect(
    screen.getByText(/Data tercatat terakhir diperbarui:/),
  ).toHaveTextContent("belum ada data");
});

it("shows unresolved IP usage without offering a misleading device history filter", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path) =>
    path.includes("/top?")
      ? {
          ...response(path),
          items: [
            {
              ...row,
              subject: "ip:192.168.1.77",
              client_id: null,
              display_name: "192.168.1.77",
              unresolved_ip: "192.168.1.77",
              latest_observation: {
                display_name: "Observed Laptop",
                mac_address: "02:00:00:00:00:77",
                observed_ns: "1792381762808974218",
              },
            },
          ],
        }
      : response(path),
  );
  mount();
  expect(await screen.findByText("192.168.1.77")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Pemilik trafik historis belum terverifikasi; IP dapat dipakai bergantian.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "192.168.1.77" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Observed Laptop")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Observed Laptop" }),
  ).not.toBeInTheDocument();
});
