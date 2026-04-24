"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import IncidentItem, IncidentPage, PageMeta
from ...api.lifecycle import apply_legacy_deprecation_headers
from ...db.session import get_db
from ...repositories.incident_repository import IncidentRepository
from ...services.observability_service import record_api_payload_request, record_api_payload_section

router = APIRouter()


@router.get("", response_model=list[IncidentItem], deprecated=True)
async def list_incidents(
    response: Response,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[IncidentItem]:
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
    db: AsyncSession = Depends(get_db),
) -> IncidentPage:
    rows, total = await IncidentRepository(db).list_incident_rows_paged(
        status=status,
        limit=limit,
        offset=offset,
        search=search,
    )
    payload_scope = str(status or "all")
    if str(search or "").strip():
        payload_scope = f"{payload_scope}+search"
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
