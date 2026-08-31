"""FastAPI routes for alerts endpoints."""

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
    """Return get active alerts used by alerting workflows."""
    apply_legacy_deprecation_headers(response, legacy_endpoint="/alerts/active")
    return [AlertItem(**row) for row in await AlertRepository(db).list_active_alert_rows(limit=limit, offset=offset)]


@router.get("/active/paged", response_model=AlertPage)
async def get_active_alerts_paged(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    severity: str | None = Query(default=None),
    site: str | None = Query(default=None),
    alert_type: str | None = Query(default=None),
    device_id: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> AlertPage:
    """Return get active alerts paged used by alerting workflows."""
    rows, total = await AlertRepository(db).list_active_alert_rows_paged(
        limit=limit,
        offset=offset,
        severity=severity,
        site=site,
        alert_type=alert_type,
        device_id=device_id,
        search=search,
    )
    scope_parts = ["active"]
    if str(severity or "").strip():
        scope_parts.append("severity")
    if str(site or "").strip():
        scope_parts.append("site")
    if str(search or "").strip():
        scope_parts.append("search")
    if str(alert_type or "").strip():
        scope_parts.append("type")
    if device_id is not None:
        scope_parts.append("device")
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
