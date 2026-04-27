"""Define module logic for `backend/app/api/routes/thresholds.py`.

This module contains project-specific implementation details.
"""

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
    """Return configured threshold key/value definitions.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return [ThresholdItem(**row) for row in await list_threshold_rows(db)]


@router.put("/{key}", response_model=ThresholdItem)
async def update_threshold(
    key: str,
    payload: ThresholdUpdate,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> ThresholdItem:
    """Update one threshold value by key.

    Args:
        key: Parameter input untuk routine ini.
        payload: Parameter input untuk routine ini.
        request: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
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
