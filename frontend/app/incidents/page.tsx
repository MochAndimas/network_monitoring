import { IncidentsDashboard } from "@/components/incidents-dashboard";
import { Suspense } from "react";

export default function IncidentsPage() {
  return <Suspense fallback={<div className="login">Memuat Incidents…</div>}><IncidentsDashboard /></Suspense>;
}
