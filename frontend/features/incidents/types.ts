export type Incident = {
  id: number; device_id: number | null; device_name: string | null; site: string | null; location: string | null; status: string; summary: string;
  owner: string | null; assignee: string | null; severity_override: string | null; effective_severity: string | null; note: string | null;
  acknowledged_at: string | null; acknowledged_by: string | null; started_at: string; ended_at: string | null; resolved_by: string | null; updated_at: string | null;
};
export type IncidentTimelineEvent = { id: number; event_type: string; actor: string | null; message: string; created_at: string };
export type IncidentPage = { items: Incident[]; meta: { total: number; limit: number; offset: number } };
export type IncidentAction = "ack" | "resolve" | "reopen";
export type IncidentWorkflow = Pick<Incident, "owner" | "assignee" | "severity_override" | "note">;
