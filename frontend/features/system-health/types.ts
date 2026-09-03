export type UnknownRecord = Record<string, unknown>;

export type SchedulerJob = {
  job_name: string;
  is_running: boolean;
  consecutive_failures: number;
  last_started_at: string | null;
  last_succeeded_at: string | null;
  last_failed_at: string | null;
  last_duration_ms: number | null;
};

export type SystemHealthSummary = {
  database: string;
  devices_total: number;
  metrics_latest_snapshot: number;
  alerts_active: number;
  incidents_active: number;
  auth: UnknownRecord;
  runtime: UnknownRecord;
  database_pool: UnknownRecord;
  scheduler_queue: UnknownRecord;
  pipeline_locks: UnknownRecord;
  raw_metric_write_rate: UnknownRecord;
  scheduler_jobs: SchedulerJob[];
  scheduler_health: UnknownRecord[];
  collector_health: UnknownRecord[];
  collector_health_window_hours?: number;
  collector_runs: UnknownRecord[];
  operational_alerts: UnknownRecord[];
};

export type FreshnessSummary = {
  generated_at: string;
  stale_after_minutes: number;
  items: Array<{ collector: string; site: string; total_devices: number; devices_with_data: number; fresh_devices: number; stale_devices: number; no_data_devices: number; freshness_status: string; latest_checked_at: string | null; oldest_checked_at: string | null }>;
};
