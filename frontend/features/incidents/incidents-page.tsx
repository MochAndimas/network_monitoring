"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch, withQuery } from "@/lib/api/client";
import { formatWib } from "@/lib/formatters";
import { DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { StatusBadge } from "@/components/ui/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/page-state";
import { PermissionGate } from "@/components/ui/permission-gate";
import { IncidentDetail } from "./incident-detail";
import type { Incident } from "./types";
type Page={items:Incident[];meta:{total:number;limit:number;offset:number}};
export function IncidentsPage(){const c=useQueryClient(),[s,setS]=useState(""),[q,setQ]=useState(""),[o,setO]=useState(0),[d,setD]=useState<Incident|null>(null);const x=useQuery({queryKey:["incidents",s,q,o],queryFn:()=>apiFetch<Page>(withQuery("/incidents/paged",{status:s,search:q,limit:50,offset:o})),refetchInterval:15000});const m=useMutation({mutationFn:({id,a}:{id:number;a:string})=>apiFetch(`/incidents/${id}/${a}`,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}),onSuccess:()=>c.invalidateQueries({queryKey:["incidents"]})});if(x.isPending)return <LoadingState/>;if(x.isError)return <ErrorState message="Insiden tidak dapat dimuat." onRetry={()=>void x.refetch()}/>;return <main className="app-page"><h1>Incidents</h1><div className="filter-panel"><label>Status<select value={s} onChange={e=>{setS(e.target.value);setO(0)}}><option value="">Semua</option><option>open</option><option>acknowledged</option><option>resolved</option></select></label><label>Cari<input value={q} onChange={e=>{setQ(e.target.value);setO(0)}}/></label></div><DataTable columns={[{key:"at",label:"Mulai",render:i=>formatWib(i.started_at)},{key:"device",label:"Device",render:i=>i.device_name??"-"},{key:"severity",label:"Severity",render:i=><StatusBadge value={i.effective_severity}/>},{key:"status",label:"Status",render:i=><StatusBadge value={i.status}/>},{key:"summary",label:"Ringkasan",render:i=>i.summary},{key:"actions",label:"Aksi",render:i=><div className="inline-actions"><button className="button-secondary" onClick={()=>setD(i)}>Detail</button><PermissionGate><button onClick={()=>m.mutate({id:i.id,a:i.status==="resolved"?"reopen":"ack"})}>{i.status==="resolved"?"Buka ulang":"Ack"}</button><button onClick={()=>m.mutate({id:i.id,a:"resolve"})}>Resolve</button></PermissionGate></div>}]} rows={x.data.items}/><Pagination offset={o} limit={50} total={x.data.meta.total} onChange={setO}/>{d&&<IncidentDetail incident={d} onClose={()=>setD(null)}/>}</main>}
