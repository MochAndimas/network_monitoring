import { Suspense } from "react";
import { LiveMonitoringV3 } from "@/components/live-monitoring-v3";
export default function LiveMonitoringPage() { return <Suspense fallback={<div className="login">Memuat Live Monitoring…</div>}><LiveMonitoringV3 /></Suspense>; }
