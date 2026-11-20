import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useQuery } from "@tanstack/react-query";
import { SystemHealthPage } from "./system-health-page";
vi.mock("@tanstack/react-query", () => ({ useQuery: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const current = {
  database: "up", devices_total: 41, metrics_latest_snapshot: 527, alerts_active: 0, incidents_active: 0,
  operational_alerts: [], scheduler_health: [], scheduler_jobs: [], database_pool: {},
  scheduler_queue: {}, pipeline_locks: {}, auth: {}, runtime: {}, notification_workers_alive: 1
};
function queries(currentResult: object, freshness: object, history: object) {
  for (const result of [currentResult, freshness, history]) {
    vi.mocked(useQuery).mockReturnValueOnce(result as ReturnType<typeof useQuery>);
  }
}
it("shows a current-status error without waiting for other requests", () => {
  queries({ isError: true, isPending: false }, { isPending: true }, { isPending: true });
  render(<SystemHealthPage />);
  expect(screen.getByRole("alert")).toHaveTextContent("30 detik");
});
it("renders current health while historical statistics and freshness are pending", () => {
  queries({ data: current }, { isPending: true }, { isPending: true });
  render(<SystemHealthPage />);
  expect(screen.getByRole("heading", { name: "System Health" })).toBeInTheDocument();
  expect(screen.getByText("41")).toBeInTheDocument();
  expect(screen.getByText("Memuat statistik collector 24 jam…")).toBeInTheDocument();
  expect(screen.getByText("Memuat freshness perangkat…")).toBeInTheDocument();
});
it("keeps auxiliary errors inline and disables the retry already in flight", () => {
  queries({ data: current }, { isError: true }, { isError: true, isFetching: true });
  render(<SystemHealthPage />);
  expect(screen.getByText("41")).toBeInTheDocument();
  const errors = screen.getAllByRole("alert");
  expect(errors).toHaveLength(2);
  for (const error of errors) expect(error).not.toHaveClass("page-state");
  expect(screen.getByRole("button", { name: "Memuat…" })).toBeDisabled();
});
it("keeps the last successful current snapshot during a refresh error", () => {
  queries({ data: current, isError: true }, { isPending: true }, { isPending: true });
  render(<SystemHealthPage />);
  expect(screen.getByText("41")).toBeInTheDocument();
});
