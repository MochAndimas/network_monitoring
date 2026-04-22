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
    """Return a list of thresholds for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `list[ThresholdItem]` result produced by the routine.
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
    """Update threshold for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        key: key value used by this routine (type `str`).
        payload: payload value used by this routine (type `ThresholdUpdate`).
        request: request value used by this routine (type `Request`).
        actor: actor value used by this routine (optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `ThresholdItem` result produced by the routine.
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
