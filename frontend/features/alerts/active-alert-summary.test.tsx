import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActiveAlertDistribution, LiveActiveAlertSummary } from "./active-alert-summary";
import { apiFetch } from "@/lib/api/client";

vi.mock("@/components/charts/plotly-chart", () => ({
  PlotlyChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
  statusChartColor: () => "#000000"
}));
vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));
afterEach(() => vi.resetAllMocks());

describe("active alert distribution", () => {
  it("shows the alert count for each severity", () => {
    render(<ActiveAlertDistribution counts={{ warning: 3, critical: 1 }} />);
    expect(screen.getByRole("row", { name: "warning 3" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: "critical 1" })).toBeInTheDocument();
    expect(screen.getByRole("img")).toBeInTheDocument();
  });

  it("shows an explicit empty state without an empty chart", () => {
    render(<ActiveAlertDistribution counts={{}} />);
    expect(screen.getByText("Tidak ada alert aktif dalam cakupan ini.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("does not present a failed request as zero alerts", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("offline"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><LiveActiveAlertSummary /></QueryClientProvider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Ringkasan alert tidak dapat dimuat.");
    expect(screen.queryByText(/0 alert aktif/)).not.toBeInTheDocument();
    queryClient.clear();
  });
});
