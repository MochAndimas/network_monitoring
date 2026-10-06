export type MetricSample = {
  id?: number;
  device_id?: number;
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
  group?: MetricGroupMeta;
  metric_names: string[];
  history: MetricSection;
  selected_device_trend: MetricSection;
  selected_device_snapshot: MetricSection;
  latest_snapshot: MetricSection;
  latest_snapshot_status_summary: Record<string, number>;
  snapshot_uptime_map: Record<string, string>;
};

export type DeviceOption = { id: number; name: string; ip_address: string; device_type: string; site: string | null };

export type MetricGroupMeta = {
    total_devices: number; device_limit: number; device_offset: number; has_more_devices: boolean;
    devices: Array<{ id: number; name: string; site: string | null; device_type: string; latest_checked_at: string | null; status: string; freshness: string }>;
    series_metric_names: string[]; metric_names_truncated: boolean; samples_per_series: number;
    max_trend_items: number; max_payload_bytes: number; value_char_limit: number; trend_sampled: boolean;
  };
