export type MetricSample = {
  device_name: string;
  metric_name: string;
  metric_value: string;
  metric_value_numeric: number | null;
  status: string | null;
  checked_at: string;
  unit: string | null;
};

export type MetricSection = {
  items: MetricSample[];
  meta: { total: number; limit: number; offset: number; sampled?: boolean };
};

export type LiveMonitoringContext = {
  metric_names: string[];
  history: MetricSection;
  selected_device_trend: MetricSection;
  latest_snapshot: MetricSection;
  latest_snapshot_status_summary: Record<string, number>;
  snapshot_uptime_map: Record<string, string>;
};

export type DeviceOption = { id: number; name: string; ip_address: string; device_type: string; site: string | null };
