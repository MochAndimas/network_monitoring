"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_write_access
from ...api.schemas import ThresholdItem, ThresholdUpdate
from ...db.session import get_db
from ...services.audit_service import record_admin_audit_log
from ...services.threshold_service import list_threshold_rows, update_threshold_value

router = APIRouter()


@router.get("", response_model=list[ThresholdItem])
async def list_thresholds(db: AsyncSession = Depends(get_db)) -> list[ThresholdItem]:
    return [ThresholdItem(**row) for row in await list_threshold_rows(db)]


@router.put("/{key}", response_model=ThresholdItem)
async def update_threshold(
    key: str,
    payload: ThresholdUpdate,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> ThresholdItem:
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
