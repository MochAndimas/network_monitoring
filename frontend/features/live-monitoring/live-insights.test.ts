import { describe, expect, it, vi } from "vitest";
vi.mock("@/components/charts/plotly-chart", () => ({ PlotlyChart: () => null, statusChartColor: () => "" }));
import { summarizeMetricHealth } from "./live-insights";
describe("metric health labels", () => {
  it("does not equate aggregate metric failures with an offline device", () => {
    expect(summarizeMetricHealth({ down: 1, warning: 2, error: 1, critical: 1 })).toEqual([["Perlu perhatian", 5]]);
  });
  it("keeps healthy and unknown totals distinct", () => {
    expect(summarizeMetricHealth({ ok: 2, up: 1, unknown: 4 })).toEqual([["Normal", 3], ["Belum diketahui", 4]]);
  });
});
