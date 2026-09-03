"""FastAPI routes for incidents endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import (
    IncidentActionRequest,
    IncidentEscalationResponse,
    IncidentItem,
    IncidentPage,
    IncidentTimelineResponse,
    IncidentWorkflowUpdate,
    PageMeta,
)
from ...api.lifecycle import apply_legacy_deprecation_headers
from ...api.deps import require_ops_access
from ...db.session import get_db
from ...repositories.incident_repository import IncidentNotFoundError, IncidentRepository
from ...services.auth_service import AuthenticatedActor
from ...services.observability_service import record_api_payload_request, record_api_payload_section

router = APIRouter()


def _actor_label(actor: AuthenticatedActor) -> str:
    """Return a compact label for timeline events."""
    if actor.user is not None:
        return actor.user.username
    if actor.api_key_name:
        return f"api_key:{actor.api_key_name}"
    return actor.kind


async def _incident_or_404(operation):
    """Translate repository not-found errors into HTTP 404 responses."""
    try:
        return await operation
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[IncidentItem], deprecated=True)
async def list_incidents(
    response: Response,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[IncidentItem]:
    """Handle the incidents endpoint."""
    apply_legacy_deprecation_headers(response, legacy_endpoint="/incidents")
    return [
        IncidentItem(**row)
        for row in await IncidentRepository(db).list_incident_rows(status=status, limit=limit, offset=offset)
    ]


@router.get("/paged", response_model=IncidentPage)
async def list_incidents_paged(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    site: str | None = Query(default=None),
    device_id: int | None = Query(default=None, ge=1),
    severity: str | None = Query(default=None, pattern="^(critical|high|warning|info)$"),
    sort: str = Query(default="newest", pattern="^(newest|severity)$"),
    db: AsyncSession = Depends(get_db),
) -> IncidentPage:
    """Handle the incidents paged endpoint."""
    rows, total = await IncidentRepository(db).list_incident_rows_paged(
        status=status,
        limit=limit,
        offset=offset,
        search=search,
        site=site,
        device_id=device_id,
        severity=severity,
        sort=sort,
    )
    payload_scope = str(status or "all")
    if str(search or "").strip():
        payload_scope = f"{payload_scope}+search"
    if str(site or "").strip():
        payload_scope = f"{payload_scope}+site"
    if severity:
        payload_scope = f"{payload_scope}+severity"
    record_api_payload_request(endpoint="/incidents/paged", scope=payload_scope)
    record_api_payload_section(
        endpoint="/incidents/paged",
        scope=payload_scope,
        section="items",
        rows=len(rows),
        total_rows=total,
        sampled=total > len(rows),
    )
    return IncidentPage(
        items=[IncidentItem(**row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/escalations", response_model=IncidentEscalationResponse)
async def list_incident_escalations(
    critical_after_minutes: int = Query(default=15, ge=1, le=1440),
    high_after_minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> IncidentEscalationResponse:
    """Return active unacknowledged incidents that need escalation."""
    rows = await IncidentRepository(db).list_escalation_rows(
        critical_after_minutes=critical_after_minutes,
        high_after_minutes=high_after_minutes,
        limit=limit,
    )
    return IncidentEscalationResponse(items=[IncidentItem(**row) for row in rows])


@router.get("/{incident_id}", response_model=IncidentItem)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
) -> IncidentItem:
    """Return one incident for frontend detail views."""
    row = await _incident_or_404(IncidentRepository(db).get_incident_row(incident_id))
    return IncidentItem(**row)


@router.get("/{incident_id}/timeline", response_model=IncidentTimelineResponse)
async def list_incident_timeline(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
) -> IncidentTimelineResponse:
    """Return one incident timeline."""
    rows = await _incident_or_404(IncidentRepository(db).list_timeline_rows(incident_id))
    return IncidentTimelineResponse(items=rows)


@router.put("/{incident_id}/workflow", response_model=IncidentItem)
async def update_incident_workflow(
    incident_id: int,
    payload: IncidentWorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_ops_access),
) -> IncidentItem:
    """Update owner, assignee, severity override, and note for an incident."""
    repository = IncidentRepository(db)
    await _incident_or_404(
        repository.update_incident_workflow(
            incident_id,
            actor=_actor_label(actor),
            owner=payload.owner,
            assignee=payload.assignee,
            severity_override=payload.severity_override,
            note=payload.note,
        )
    )
    return IncidentItem(**await _incident_or_404(repository.get_incident_row(incident_id)))


@router.post("/{incident_id}/ack", response_model=IncidentItem)
async def acknowledge_incident(
    incident_id: int,
    payload: IncidentActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_ops_access),
) -> IncidentItem:
    """Acknowledge an active incident."""
    repository = IncidentRepository(db)
    await _incident_or_404(
        repository.acknowledge_incident(
            incident_id,
            actor=_actor_label(actor),
            note=payload.note if payload else None,
            assignee=payload.assignee if payload else None,
        )
    )
    return IncidentItem(**await _incident_or_404(repository.get_incident_row(incident_id)))


@router.post("/{incident_id}/resolve", response_model=IncidentItem)
async def resolve_incident(
    incident_id: int,
    payload: IncidentActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_ops_access),
) -> IncidentItem:
    """Resolve an incident manually."""
    repository = IncidentRepository(db)
    await _incident_or_404(
        repository.manually_resolve_incident(
            incident_id,
            actor=_actor_label(actor),
            note=payload.note if payload else None,
        )
    )
    return IncidentItem(**await _incident_or_404(repository.get_incident_row(incident_id)))


@router.post("/{incident_id}/reopen", response_model=IncidentItem)
async def reopen_incident(
    incident_id: int,
    payload: IncidentActionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_ops_access),
) -> IncidentItem:
    """Reopen a resolved incident."""
    repository = IncidentRepository(db)
    await _incident_or_404(
        repository.reopen_incident(
            incident_id,
            actor=_actor_label(actor),
            note=payload.note if payload else None,
        )
    )
    return IncidentItem(**await _incident_or_404(repository.get_incident_row(incident_id)))
