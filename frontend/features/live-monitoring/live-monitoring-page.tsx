"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CsvExport } from "@/components/ui/csv-export";
import { DataTable } from "@/components/ui/data-table";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { StatusBadge } from "@/components/ui/status-badge";
import { apiFetch, withQuery } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { LiveInsights } from "./live-insights";
import { MikrotikDetail } from "./mikrotik-detail";
import { NasDetail } from "./nas-detail";
import { LiveTrends } from "./live-trends";
import { isMikrotikDevice, trendMetricNames } from "./trend-utils";
import type { DeviceOption, LiveMonitoringContext, MetricSample } from "./types";

const SNAPSHOT_LIMIT = 10;
const HISTORY_LIMIT = 100;

function displayValue(item: MetricSample) {
  return `${item.metric_value}${item.unit ? ` ${item.unit}` : ""}`;
}

export function LiveMonitoringPage() {
  const [deviceId, setDeviceId] = useState("");
  const [metric, setMetric] = useState("");
  const [status, setStatus] = useState("");
  const [chartWindowHours, setChartWindowHours] = useState(6);
  const [snapshotOffset, setSnapshotOffset] = useState(0);
  const devices = useQuery({ queryKey: ["devices", "options"], queryFn: () => apiFetch<DeviceOption[]>("/devices/options?active_only=true") });
  const selectedDevice = devices.data?.find((device) => String(device.id) === deviceId);
  const selectedIsMikrotik = isMikrotikDevice(selectedDevice?.device_type, selectedDevice?.name);
  const selectedIsNas = selectedDevice?.device_type === "nas";
  const deviceMetrics = useQuery({
    queryKey: ["metrics", "names", deviceId],
    queryFn: () => apiFetch<string[]>(withQuery("/metrics/names", { device_id: deviceId })),
    enabled: Boolean(deviceId)
  });
  const selectedTrendMetrics = trendMetricNames(selectedIsMikrotik ? "mikrotik" : selectedDevice?.device_type, deviceMetrics.data ?? [], metric);
  const monitoring = useQuery({
    queryKey: ["live-monitoring", deviceId, metric, status, chartWindowHours, selectedTrendMetrics, snapshotOffset],
    queryFn: () => apiFetch<LiveMonitoringContext>(withQuery("/metrics/history/live", {
      device_id: deviceId || undefined,
      metric_name: metric || undefined,
      status: status || undefined,
      limit: HISTORY_LIMIT,
      snapshot_limit: SNAPSHOT_LIMIT,
      snapshot_offset: snapshotOffset,
      include_selected_device_trend: Boolean(deviceId),
      include_selected_device_snapshot: selectedIsMikrotik || selectedIsNas,
      trend_metric_names: selectedTrendMetrics,
      trend_limit: 500
    })),
    refetchInterval: 15_000
  });

  if (monitoring.isPending || devices.isPending || (deviceMetrics.isPending && Boolean(deviceId))) return <LoadingState />;
  if (monitoring.isError || devices.isError || deviceMetrics.isError) return <ErrorState message="Live monitoring tidak dapat dimuat." onRetry={() => { void monitoring.refetch(); void devices.refetch(); void deviceMetrics.refetch(); }} />;

  const data = monitoring.data;
  const metricOptions = deviceId ? deviceMetrics.data ?? [] : data.metric_names;
  const anomalies = data.latest_snapshot.items.filter((item) => ["warning", "down", "error"].includes(String(item.status))).length;
  const monitoredDevices = new Set(data.latest_snapshot.items.map((item) => item.device_name)).size;
  const snapshotColumns = [
    { key: "device", label: "Device", render: (item: MetricSample) => item.device_name },
    { key: "metric", label: "Metrik", render: (item: MetricSample) => item.metric_name },
    { key: "value", label: "Nilai terakhir", render: displayValue },
    { key: "uptime", label: "Uptime", render: (item: MetricSample) => data.snapshot_uptime_map[item.device_name] ?? "-" },
    { key: "status", label: "Status", render: (item: MetricSample) => <StatusBadge value={item.status} /> },
    { key: "time", label: "Dicek (WIB)", render: (item: MetricSample) => formatWib(item.checked_at) }
  ];
  const historyColumns = [
    { key: "time", label: "Dicek (WIB)", render: (item: MetricSample) => formatWib(item.checked_at) },
    { key: "device", label: "Device", render: (item: MetricSample) => item.device_name },
    { key: "metric", label: "Metrik", render: (item: MetricSample) => item.metric_name },
    { key: "value", label: "Nilai", render: displayValue },
    { key: "numeric", label: "Nilai numerik", render: (item: MetricSample) => item.metric_value_numeric ?? "-" },
    { key: "status", label: "Status", render: (item: MetricSample) => <StatusBadge value={item.status} /> }
  ];

  function resetSnapshot() { setSnapshotOffset(0); }
  return <main className="app-page">
    <PageHeader title="Live Monitoring" description="Snapshot 24 jam terakhir, riwayat metric, dan trend perangkat secara real-time." />
    <MetricGrid columns={5}>
      <MetricCard label="Total data" value={data.history.meta.total.toLocaleString("id-ID")} />
      <MetricCard label="Device terpantau" value={monitoredDevices.toLocaleString("id-ID")} />
      <MetricCard label="Metrik aktif" value={data.metric_names.length.toLocaleString("id-ID")} />
      <MetricCard label="Anomali aktif" value={anomalies.toLocaleString("id-ID")} />
      <MetricCard label="Pengecekan terakhir" value={formatWib(data.latest_snapshot.items[0]?.checked_at)} />
    </MetricGrid>

    <div className="filter-panel">
      <label>Device<select value={deviceId} onChange={(event) => { setDeviceId(event.target.value); resetSnapshot(); }}><option value="">Semua device</option>{devices.data.map((device) => <option key={device.id} value={device.id}>{device.name} · {device.ip_address}</option>)}</select></label>
      <label>Metrik<select value={metric} onChange={(event) => { setMetric(event.target.value); resetSnapshot(); }}><option value="">Semua metrik</option>{metricOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label>Status<select value={status} onChange={(event) => { setStatus(event.target.value); resetSnapshot(); }}><option value="">Semua status</option>{["ok", "warning", "down", "error"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label>Window chart<select value={chartWindowHours} onChange={(event) => setChartWindowHours(Number(event.target.value))}><option value={1}>1 jam</option><option value={6}>6 jam</option><option value={12}>12 jam</option><option value={24}>24 jam</option></select></label>
    </div>

    <LiveInsights samples={data.latest_snapshot.items} statusSummary={data.latest_snapshot_status_summary} />

    {selectedIsMikrotik ? <MikrotikDetail samples={data.selected_device_snapshot.items} /> : null}
    {selectedIsNas ? <NasDetail samples={data.selected_device_snapshot.items} /> : null}
    <LiveTrends deviceName={selectedDevice?.name} selectedMetric={metric} samples={data.selected_device_trend.items} windowHours={chartWindowHours} />

    <section>
      <div className="section-header"><h2>Snapshot Terbaru</h2><CsvExport filename="live-snapshot.csv" columns={["Device", "Metrik", "Nilai", "Uptime", "Status", "Dicek WIB"]} rows={data.latest_snapshot.items.map((item) => [item.device_name, item.metric_name, displayValue(item), data.snapshot_uptime_map[item.device_name], item.status, formatWib(item.checked_at)])} /></div>
      <DataTable columns={snapshotColumns} rows={data.latest_snapshot.items} />
      <Pagination offset={snapshotOffset} limit={SNAPSHOT_LIMIT} total={data.latest_snapshot.meta.total} onChange={setSnapshotOffset} />
    </section>

    <section>
      <div className="section-header"><h2>Anomali Terbaru</h2><CsvExport filename="live-anomali.csv" columns={["Dicek WIB", "Device", "Metrik", "Nilai", "Status"]} rows={data.latest_snapshot.items.filter((item) => ["warning", "down", "error"].includes(String(item.status))).map((item) => [formatWib(item.checked_at), item.device_name, item.metric_name, displayValue(item), item.status])} /></div>
      <DataTable columns={historyColumns} rows={data.latest_snapshot.items.filter((item) => ["warning", "down", "error"].includes(String(item.status)))} emptyLabel="Tidak ada anomali aktif." />
    </section>

    <section>
      <div className="section-header"><h2>Riwayat Detail</h2><CsvExport filename="live-history.csv" columns={["Dicek WIB", "Device", "Metrik", "Nilai", "Nilai numerik", "Status"]} rows={data.history.items.map((item) => [formatWib(item.checked_at), item.device_name, item.metric_name, displayValue(item), item.metric_value_numeric, item.status])} /></div>
      <DataTable columns={historyColumns} rows={data.history.items} />
    </section>
  </main>;
}
