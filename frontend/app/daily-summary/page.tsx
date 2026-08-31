import { DailySummaryDashboard } from "@/components/daily-summary-dashboard";
import { Suspense } from "react";

export default function DailySummaryPage() {
  return <Suspense fallback={<div className="login">Memuat Daily Summary…</div>}><DailySummaryDashboard /></Suspense>;
}
