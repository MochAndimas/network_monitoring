"""FastAPI routes for thresholds and alert intelligence controls."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_write_access
from ...api.schemas import (
    MaintenanceWindowCreate,
    MaintenanceWindowItem,
    ThresholdItem,
    ThresholdOverrideCreate,
    ThresholdOverrideItem,
    ThresholdUpdate,
)
from ...db.session import get_db
from ...services.audit_service import record_admin_audit_log
from ...services.auth_service import AuthenticatedActor
from ...services.threshold_service import (
    create_maintenance_window,
    create_threshold_override,
    deactivate_maintenance_window,
    deactivate_threshold_override,
    list_maintenance_window_rows,
    list_threshold_override_rows,
    list_threshold_rows,
    update_threshold_value,
)

router = APIRouter()


def _actor_label(actor: AuthenticatedActor) -> str:
    if actor.user is not None:
        return actor.user.username
    if actor.api_key_name:
        return f"api_key:{actor.api_key_name}"
    return actor.kind


@router.get("", response_model=list[ThresholdItem])
async def list_thresholds(db: AsyncSession = Depends(get_db)) -> list[ThresholdItem]:
    """Handle the thresholds endpoint."""
    return [ThresholdItem(**row) for row in await list_threshold_rows(db)]


@router.put("/{key}", response_model=ThresholdItem)
async def update_threshold(
    key: str,
    payload: ThresholdUpdate,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> ThresholdItem:
    """Handle the threshold endpoint."""
    threshold = await update_threshold_value(db, key, payload.value)
    await record_admin_audit_log(
        db,
        actor=actor,
        action="threshold.update",
        target_type="threshold",
        target_id=key,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details={"value": payload.value},
    )
    return ThresholdItem(**threshold)


@router.get("/overrides", response_model=list[ThresholdOverrideItem])
async def list_threshold_overrides(db: AsyncSession = Depends(get_db)) -> list[ThresholdOverrideItem]:
    """List scoped threshold overrides."""
    return [ThresholdOverrideItem(**row) for row in await list_threshold_override_rows(db)]


@router.post("/overrides", response_model=ThresholdOverrideItem)
async def create_threshold_override_endpoint(
    payload: ThresholdOverrideCreate,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> ThresholdOverrideItem:
    """Create a scoped threshold override."""
    row = await create_threshold_override(db, payload.model_dump())
    await record_admin_audit_log(
        db,
        actor=actor,
        action="threshold_override.create",
        target_type="threshold_override",
        target_id=str(row["id"]),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details=row,
    )
    return ThresholdOverrideItem(**row)


@router.delete("/overrides/{override_id}")
async def deactivate_threshold_override_endpoint(
    override_id: int,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deactivate a scoped threshold override."""
    if not await deactivate_threshold_override(db, override_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Threshold override not found")
    await record_admin_audit_log(
        db,
        actor=actor,
        action="threshold_override.deactivate",
        target_type="threshold_override",
        target_id=str(override_id),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details={},
    )
    return {"ok": True}


@router.get("/maintenance-windows", response_model=list[MaintenanceWindowItem])
async def list_maintenance_windows(db: AsyncSession = Depends(get_db)) -> list[MaintenanceWindowItem]:
    """List maintenance windows."""
    return [MaintenanceWindowItem(**row) for row in await list_maintenance_window_rows(db)]


@router.post("/maintenance-windows", response_model=MaintenanceWindowItem)
async def create_maintenance_window_endpoint(
    payload: MaintenanceWindowCreate,
    request: Request,
    actor: AuthenticatedActor = Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceWindowItem:
    """Create an alert suppression maintenance window."""
    row = await create_maintenance_window(db, payload.model_dump(), actor=_actor_label(actor))
    await record_admin_audit_log(
        db,
        actor=actor,
        action="maintenance_window.create",
        target_type="maintenance_window",
        target_id=str(row["id"]),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details=row,
    )
    return MaintenanceWindowItem(**row)


@router.delete("/maintenance-windows/{window_id}")
async def deactivate_maintenance_window_endpoint(
    window_id: int,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deactivate a maintenance window."""
    if not await deactivate_maintenance_window(db, window_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance window not found")
    await record_admin_audit_log(
        db,
        actor=actor,
        action="maintenance_window.deactivate",
        target_type="maintenance_window",
        target_id=str(window_id),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details={},
    )
    return {"ok": True}
