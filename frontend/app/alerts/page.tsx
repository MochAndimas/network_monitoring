import { AlertsDashboard } from "@/components/alerts-dashboard";
import { Suspense } from "react";

export default function AlertsPage() {
  return <Suspense fallback={<div className="login">Memuat Alerts…</div>}><AlertsDashboard /></Suspense>;
}
