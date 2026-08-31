"use client";

import { LiveMonitoringV2 } from "@/components/live-monitoring-v2";

/**
 * Dedicated migration boundary for the Streamlit Live Monitoring parity work.
 * New cards, exports, pagination, and device-specific panels are added here.
 */
export function LiveMonitoringV3() {
  return <LiveMonitoringV2 />;
}
