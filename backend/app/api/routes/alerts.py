"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import AlertItem, AlertPage, PageMeta
from ...api.lifecycle import apply_legacy_deprecation_headers
from ...db.session import get_db
from ...repositories.alert_repository import AlertRepository
from ...services.observability_service import record_api_payload_request, record_api_payload_section

router = APIRouter()


@router.get("/active", response_model=list[AlertItem], deprecated=True)
async def get_active_alerts(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[AlertItem]:
    apply_legacy_deprecation_headers(response, legacy_endpoint="/alerts/active")
    return [AlertItem(**row) for row in await AlertRepository(db).list_active_alert_rows(limit=limit, offset=offset)]


@router.get("/active/paged", response_model=AlertPage)
async def get_active_alerts_paged(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    severity: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> AlertPage:
    rows, total = await AlertRepository(db).list_active_alert_rows_paged(
        limit=limit,
        offset=offset,
        severity=severity,
        search=search,
    )
    scope_parts = ["active"]
    if str(severity or "").strip():
        scope_parts.append("severity")
    if str(search or "").strip():
        scope_parts.append("search")
    payload_scope = "+".join(scope_parts)
    record_api_payload_request(endpoint="/alerts/active/paged", scope=payload_scope)
    record_api_payload_section(
        endpoint="/alerts/active/paged",
        scope=payload_scope,
        section="items",
        rows=len(rows),
        total_rows=total,
        sampled=total > len(rows),
    )
    return AlertPage(items=[AlertItem(**row) for row in rows], meta=PageMeta(total=total, limit=limit, offset=offset))
