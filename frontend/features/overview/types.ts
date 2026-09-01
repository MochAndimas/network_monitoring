export type OverviewData = {
  summary: { internet_status: string; mikrotik_status: string; server_status: string; active_alerts: number };
  device_counts: { total: number; active: number; statuses: Record<string, number>; latest_check_at: string | null };
  alert_severity_summary: Record<string, number>;
  problem_devices: Array<{ name: string; ip_address: string; device_type: string; site: string | null; latest_status: string; latest_checked_at: string | null }>;
  alerts: Array<{ created_at: string; device_name: string; severity: string; message: string }>;
  incidents: Array<{ started_at: string; device_name: string; summary: string; status: string }>;
  latest_snapshot: { items: Array<{ checked_at: string; device_name: string; metric_name: string; metric_value: string | number; unit: string | null; status: string }> };
};
