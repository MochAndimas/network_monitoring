"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { CsvExport } from "@/components/ui/csv-export";
import { DataTable } from "@/components/ui/data-table";
import { MetricCard, MetricGrid } from "@/components/ui/metric-card";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { CursorPagination } from "@/components/ui/cursor-pagination";
import { StatusBadge } from "@/components/ui/status-badge";
import { apiFetch, withQuery } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { initialOffset, useUrlQuerySync } from "@/lib/use-url-query-sync";
import { toWibOffsetTimestamp } from "@/lib/wib-time";
import { LiveInsights } from "./live-insights";
import { MikrotikDetail } from "./mikrotik-detail";
import { NasDetail } from "./nas-detail";
import { PrinterDetail } from "./printer-detail";
import { DeviceGroupDetail } from "./voip-detail";
import { LiveTrends } from "./live-trends";
import { isMikrotikDevice, trendMetricNames } from "./trend-utils";
import type { DeviceOption, LiveMonitoringContext, MetricSample } from "./types";

const SNAPSHOT_LIMIT = 10;
const HISTORY_LIMIT = 100;

type MonitoringMode = "live" | "range";

function displayValue(item: MetricSample) {
  return `${item.metric_value}${item.unit ? ` ${item.unit}` : ""}`;
}

function wibDateInput(daysAgo = 0) {
  const date = new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const value = (partType: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === partType)?.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}

function wibRangeBoundary(date: string, endOfDay = false) {
  return `${date}T${endOfDay ? "23:59:59" : "00:00:00"}+07:00`;
}

function liveRange() {
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  return { checked_from: toWibOffsetTimestamp(start), checked_to: toWibOffsetTimestamp(end) };
}

function initialChartWindow(value: string | null) {
  const parsed = Number(value);
  return [1, 6, 12, 24].includes(parsed) ? parsed : 6;
}

export function LiveMonitoringPage() {
  const params = useSearchParams();
  const [deviceId, setDeviceId] = useState(() => params.get("device") ?? "");
  const [metric, setMetric] = useState(() => params.get("metric") ?? "");
  const [status, setStatus] = useState(() => params.get("status") ?? "");
  const [monitoringMode, setMonitoringMode] = useState<MonitoringMode>(() => params.get("mode") === "range" ? "range" : "live");
  const [rangeFrom, setRangeFrom] = useState(() => params.get("from") ?? wibDateInput(1));
  const [rangeTo, setRangeTo] = useState(() => params.get("to") ?? wibDateInput());
  const [chartWindowHours, setChartWindowHours] = useState(() => initialChartWindow(params.get("window")));
  const [snapshotOffset, setSnapshotOffset] = useState(() => initialOffset(params.get("snapshot_offset")));
  const [historyCursor, setHistoryCursor] = useState<string | undefined>();
  const [historyCursorTrail, setHistoryCursorTrail] = useState<Array<string | undefined>>([]);
  useUrlQuerySync({ device: deviceId, metric, status, mode: monitoringMode === "range" ? monitoringMode : undefined, from: monitoringMode === "range" ? rangeFrom : undefined, to: monitoringMode === "range" ? rangeTo : undefined, window: chartWindowHours === 6 ? undefined : chartWindowHours, snapshot_offset: snapshotOffset });
  const devices = useQuery({ queryKey: ["devices", "options"], queryFn: () => apiFetch<DeviceOption[]>("/devices/options?active_only=true") });
  const isVoipGroup = deviceId === "__voip__";
  const isRuijieGroup = deviceId === "__ruijie__";
  // Group values are client-side options, not API device identifiers.
  const isDeviceGroup = isVoipGroup || isRuijieGroup;
  const apiDeviceId = isDeviceGroup ? undefined : deviceId || undefined;
  const voipDevices = devices.data?.filter((device) => device.device_type === "voip") ?? [];
  const ruijieDevices = devices.data?.filter((device) => device.device_type.toLowerCase() === "ruijie" || device.name.toLowerCase().includes("ruijie")) ?? [];
  const groupedDevices = isVoipGroup ? voipDevices : ruijieDevices;
  const groupLabel = isVoipGroup ? "VoIP" : "Ruijie";
  const groupKey = isVoipGroup ? "voip" : "ruijie";
  const selectableDevices = devices.data?.filter((device) => device.device_type !== "voip" && !ruijieDevices.some((ruijie) => ruijie.id === device.id)) ?? [];
  const selectedDevice = devices.data?.find((device) => String(device.id) === deviceId);
  const selectedIsMikrotik = isMikrotikDevice(selectedDevice?.device_type, selectedDevice?.name);
  const selectedIsNas = selectedDevice?.device_type === "nas";
  const selectedIsPrinter = selectedDevice?.device_type === "printer";
  const isRangeMode = monitoringMode === "range";
  const hasValidRange = !isRangeMode || (rangeFrom.length > 0 && rangeTo.length > 0 && rangeFrom <= rangeTo);
  const historyEndpoint = isRangeMode ? "/metrics/history/context" : "/metrics/history/live";
  const historyRange = isRangeMode ? { checked_from: wibRangeBoundary(rangeFrom), checked_to: wibRangeBoundary(rangeTo, true) } : {};
  const refreshInterval = isRangeMode ? false : 15_000;
  const groupMetricNames = useQuery({ queryKey: ["metrics", "names", groupKey], queryFn: () => apiFetch<string[]>(withQuery("/metrics/names", { device_id: groupedDevices[0]?.id })), enabled: isDeviceGroup && groupedDevices.length > 0 });
  const deviceMetrics = useQuery({
    queryKey: ["metrics", "names", deviceId],
    queryFn: () => apiFetch<string[]>(withQuery("/metrics/names", { device_id: deviceId })),
    enabled: Boolean(deviceId) && !isDeviceGroup
  });
  const selectedTrendMetrics = isDeviceGroup ? (metric ? [metric] : groupMetricNames.data ?? []) : trendMetricNames(selectedIsMikrotik ? "mikrotik" : selectedDevice?.device_type, deviceMetrics.data ?? [], metric);
  const groupHistory = useQueries({ queries: groupedDevices.map((device) => ({
    queryKey: ["live-monitoring", monitoringMode, rangeFrom, rangeTo, groupKey, device.id, metric, status, selectedTrendMetrics],
    queryFn: () => apiFetch<LiveMonitoringContext>(withQuery(historyEndpoint, { device_id: device.id, metric_name: metric || undefined, status: status || undefined, include_selected_device_trend: true, trend_metric_names: selectedTrendMetrics, trend_limit: 500, limit: 500, ...historyRange })),
    enabled: isDeviceGroup && selectedTrendMetrics.length > 0 && hasValidRange,
    refetchInterval: refreshInterval
  })) });
  const monitoring = useQuery({
    queryKey: ["live-monitoring", monitoringMode, rangeFrom, rangeTo, deviceId, metric, status, chartWindowHours, selectedTrendMetrics, snapshotOffset],
    queryFn: () => apiFetch<LiveMonitoringContext>(withQuery(historyEndpoint, {
      device_id: apiDeviceId,
      metric_name: metric || undefined,
      status: status || undefined,
      limit: HISTORY_LIMIT,
      snapshot_limit: SNAPSHOT_LIMIT,
      snapshot_offset: snapshotOffset,
      include_selected_device_trend: Boolean(apiDeviceId),
      include_selected_device_snapshot: selectedIsMikrotik || selectedIsNas || selectedIsPrinter,
      trend_metric_names: selectedTrendMetrics,
      trend_limit: 500,
      ...historyRange
    })),
    enabled: hasValidRange,
    refetchInterval: refreshInterval
  });
  const pagedHistoryRange = isRangeMode ? { checked_from: wibRangeBoundary(rangeFrom), checked_to: wibRangeBoundary(rangeTo, true) } : liveRange();
  const historyPage = useQuery({ queryKey: ["live-history-page", apiDeviceId, metric, status, monitoringMode, rangeFrom, rangeTo, historyCursor], queryFn: () => apiFetch<{ items: MetricSample[]; meta: { total: number | null; limit: number; next_cursor: string | null; has_more: boolean } }>(withQuery("/metrics/history/paged", { device_id: apiDeviceId, metric_name: metric || undefined, status: status || undefined, limit: 10, cursor: historyCursor, ...pagedHistoryRange })), enabled: !isDeviceGroup && hasValidRange });

  if (!hasValidRange) return <ErrorState message="Tanggal mulai harus diisi dan tidak boleh melewati tanggal akhir." onRetry={() => undefined} />;
  if (monitoring.isPending || devices.isPending || (deviceMetrics.isPending && Boolean(deviceId) && !isDeviceGroup) || (isDeviceGroup && groupMetricNames.isPending)) return <LoadingState />;
  if (monitoring.isError || historyPage.isError || devices.isError || deviceMetrics.isError || groupMetricNames.isError || groupHistory.some((query) => query.isError)) return <ErrorState message="Live monitoring tidak dapat dimuat." onRetry={() => { void monitoring.refetch(); void historyPage.refetch(); void devices.refetch(); void deviceMetrics.refetch(); void groupMetricNames.refetch(); groupHistory.forEach((query) => void query.refetch()); }} />;

  const data = monitoring.data;
  const metricOptions = isDeviceGroup ? groupMetricNames.data ?? [] : deviceId ? deviceMetrics.data ?? [] : data.metric_names;
  const groupSamples = groupHistory.flatMap((query) => query.data?.selected_device_trend.items ?? []);
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

  function resetSnapshot() { setSnapshotOffset(0); setHistoryCursor(undefined); setHistoryCursorTrail([]); }
  function nextHistoryPage() {
    const nextCursor = historyPage.data?.meta.next_cursor;
    if (!nextCursor) return;
    setHistoryCursorTrail((trail) => [...trail, historyCursor]);
    setHistoryCursor(nextCursor);
  }
  function previousHistoryPage() {
    setHistoryCursorTrail((trail) => {
      const previousCursor = trail[trail.length - 1];
      setHistoryCursor(previousCursor);
      return trail.slice(0, -1);
    });
  }
  return <main className="app-page live-monitoring-page">
    <PageHeader className="live-monitoring-header" title="Live Monitoring" description={isRangeMode ? `Riwayat metric untuk rentang ${rangeFrom} s.d. ${rangeTo}.` : "Snapshot 24 jam terakhir, riwayat metric, dan trend perangkat secara real-time."} />
    <MetricGrid columns={5}>
      <MetricCard label="Total data" value={data.history.meta.total.toLocaleString("id-ID")} />
      <MetricCard label="Device terpantau" value={monitoredDevices.toLocaleString("id-ID")} />
      <MetricCard label="Metrik aktif" value={data.metric_names.length.toLocaleString("id-ID")} />
      <MetricCard label="Anomali aktif" value={anomalies.toLocaleString("id-ID")} />
      <MetricCard label="Pengecekan terakhir" value={formatWib(data.latest_snapshot.items[0]?.checked_at)} />
    </MetricGrid>

    <div className="filter-panel">
      <label>Device<select value={deviceId} onChange={(event) => { setDeviceId(event.target.value); resetSnapshot(); }}><option value="">Semua device</option>{voipDevices.length ? <option value="__voip__">Semua VoIP</option> : null}{ruijieDevices.length ? <option value="__ruijie__">Semua Ruijie</option> : null}{selectableDevices.map((device) => <option key={device.id} value={device.id}>{device.name} · {device.ip_address}</option>)}</select></label>
      <label>Metrik<select value={metric} onChange={(event) => { setMetric(event.target.value); resetSnapshot(); }}><option value="">Semua metrik</option>{metricOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label>Status<select value={status} onChange={(event) => { setStatus(event.target.value); resetSnapshot(); }}><option value="">Semua status</option>{["ok", "warning", "down", "error"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label>Mode data<select value={monitoringMode} onChange={(event) => { setMonitoringMode(event.target.value as MonitoringMode); resetSnapshot(); }}><option value="live">Live (24 jam)</option><option value="range">Rentang tanggal</option></select></label>
      {isRangeMode ? <><label>Tanggal mulai<input type="date" value={rangeFrom} max={rangeTo} onChange={(event) => { setRangeFrom(event.target.value); resetSnapshot(); }} /></label><label>Tanggal akhir<input type="date" value={rangeTo} min={rangeFrom} onChange={(event) => { setRangeTo(event.target.value); resetSnapshot(); }} /></label></> : null}
      <label>Window chart<select value={chartWindowHours} onChange={(event) => setChartWindowHours(Number(event.target.value))}><option value={1}>1 jam</option><option value={6}>6 jam</option><option value={12}>12 jam</option><option value={24}>24 jam</option></select></label>
    </div>

    <LiveInsights samples={data.latest_snapshot.items} statusSummary={data.latest_snapshot_status_summary} />

    {selectedIsMikrotik ? <MikrotikDetail samples={data.selected_device_snapshot.items} /> : null}
    {selectedIsNas ? <NasDetail samples={data.selected_device_snapshot.items} /> : null}
    {selectedIsPrinter ? <PrinterDetail samples={data.selected_device_snapshot.items} /> : null}
    {isDeviceGroup ? <DeviceGroupDetail samples={groupSamples} selectedMetric={metric} windowHours={chartWindowHours} label={groupLabel} /> : <LiveTrends deviceName={selectedDevice?.name} selectedMetric={metric} samples={data.selected_device_trend.items} windowHours={chartWindowHours} />}

    <section className="live-monitoring-data-section">
      <div className="section-header"><h2>Snapshot Terbaru</h2><CsvExport filename="live-snapshot.csv" columns={["Device", "Metrik", "Nilai", "Uptime", "Status", "Dicek WIB"]} rows={data.latest_snapshot.items.map((item) => [item.device_name, item.metric_name, displayValue(item), data.snapshot_uptime_map[item.device_name], item.status, formatWib(item.checked_at)])} /></div>
      <DataTable columns={snapshotColumns} rows={data.latest_snapshot.items} />
      <Pagination offset={snapshotOffset} limit={SNAPSHOT_LIMIT} total={data.latest_snapshot.meta.total} onChange={setSnapshotOffset} />
    </section>

    <section className="live-monitoring-data-section">
      <div className="section-header"><h2>Anomali Terbaru</h2><CsvExport filename="live-anomali.csv" columns={["Dicek WIB", "Device", "Metrik", "Nilai", "Status"]} rows={data.latest_snapshot.items.filter((item) => ["warning", "down", "error"].includes(String(item.status))).map((item) => [formatWib(item.checked_at), item.device_name, item.metric_name, displayValue(item), item.status])} /></div>
      <DataTable columns={historyColumns} rows={data.latest_snapshot.items.filter((item) => ["warning", "down", "error"].includes(String(item.status)))} emptyLabel="Tidak ada anomali aktif." />
    </section>

    <section className="live-monitoring-data-section">
      <div className="section-header"><h2>Riwayat Detail</h2><CsvExport filename="live-history.csv" columns={["Dicek WIB", "Device", "Metrik", "Nilai", "Nilai numerik", "Status"]} rows={(historyPage.data?.items ?? data.history.items).map((item) => [formatWib(item.checked_at), item.device_name, item.metric_name, displayValue(item), item.metric_value_numeric, item.status])} /></div>
      <DataTable columns={historyColumns} rows={historyPage.data?.items ?? data.history.items} />
      {historyPage.data ? <CursorPagination itemCount={historyPage.data.items.length} limit={historyPage.data.meta.limit} total={historyPage.data.meta.total} pageIndex={historyCursorTrail.length} hasNext={historyPage.data.meta.has_more} hasPrevious={historyCursorTrail.length > 0} onNext={nextHistoryPage} onPrevious={previousHistoryPage} /> : null}
    </section>
  </main>;
}
