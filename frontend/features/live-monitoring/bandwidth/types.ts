/** Decimal counters and epoch nanoseconds intentionally remain strings. */
export type UsageRow = {
  day: string | null;
  subject: string | null;
  client_id: number | null;
  display_name: string | null;
  unresolved_ip: string | null;
  latest_observation?: {
    display_name: string;
    mac_address: string;
    observed_ns: string;
  } | null;
  upload_bytes: string;
  download_bytes: string;
  total_bytes: string;
  estimated_bytes: string;
  unresolved_bytes: string;
  updated_ns: string;
};

export type UsagePage = {
  router_id: number;
  start: string;
  end: string;
  timezone: "Asia/Jakarta";
  allocation: "proportional_integer_v1";
  completeness: "unverified";
  items: UsageRow[];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type BandwidthClient = {
  id: number;
  mac_address: string;
  hostname: string | null;
  custom_name: string | null;
  display_name: string;
  first_seen_ns: string;
  last_seen_ns: string;
};

export type ClientPage = {
  items: BandwidthClient[];
  next_after_id: number | null;
};
export type ReportRange = { start: string; end: string };
