"use client";

import dynamic from "next/dynamic";
import type { PlotParams } from "react-plotly.js";

const Plot = dynamic<PlotParams>(() => import("react-plotly.js"), { ssr: false, loading: () => <div className="chart-loading">Memuat visual…</div> });

const baseLayout: Partial<PlotParams["layout"]> = {
  paper_bgcolor: "#172033", plot_bgcolor: "#172033", font: { color: "#edf3ff" }, margin: { l: 54, r: 22, t: 26, b: 48 }, autosize: true
};

const STATUS_CHART_COLORS: Record<string, string> = {
  up: "#8df0c3", ok: "#8df0c3", warning: "#ffe191", down: "#ffb5b8", error: "#ffb5b8",
  critical: "#ffb5b8", high: "#ffb5b8", active: "#a8d8ff", resolved: "#d3dce8"
};

export function statusChartColor(status: string) {
  return STATUS_CHART_COLORS[status.toLowerCase()] ?? "#d3dce8";
}

export function PlotlyChart({ data, layout, ariaLabel }: Pick<PlotParams, "data"> & { layout?: Partial<PlotParams["layout"]>; ariaLabel: string }) {
  return <div className="chart-wrap" role="img" aria-label={ariaLabel}><Plot data={data} layout={{ ...baseLayout, ...layout }} config={{ displayModeBar: false, responsive: true }} useResizeHandler style={{ width: "100%", height: "100%" }} /></div>;
}
