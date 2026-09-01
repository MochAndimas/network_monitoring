"use client";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { LoadingState, ErrorState } from "@/components/ui/page-state";
import type { Incident, IncidentTimelineEvent } from "./types";

export function IncidentDetail({ incident, onClose }: { incident: Incident; onClose: () => void }) {
  const timeline = useQuery({ queryKey: ["incident", incident.id, "timeline"], queryFn: () => apiFetch<{ items: IncidentTimelineEvent[] }>(`/incidents/${incident.id}/timeline`) });
  return <div className="dialog-backdrop"><section className="dialog" role="dialog" aria-modal="true"><header className="section-header"><h2>Insiden #{incident.id}</h2><button className="button-secondary" onClick={onClose}>Tutup</button></header><p>{incident.summary}</p><dl className="meta-strip"><div><dt>Device</dt><dd>{incident.device_name ?? "-"}</dd></div><div><dt>Mulai</dt><dd>{formatWib(incident.started_at)}</dd></div><div><dt>Status</dt><dd>{incident.status}</dd></div></dl><h3>Timeline</h3>{timeline.isPending ? <LoadingState /> : timeline.isError ? <ErrorState message="Timeline tidak dapat dimuat." onRetry={() => void timeline.refetch()} /> : <ol>{timeline.data.items.map((item) => <li key={item.id}><strong>{item.event_type}</strong> — {item.message} <small>{formatWib(item.created_at)} · {item.actor ?? "system"}</small></li>)}</ol>}</section></div>;
}
