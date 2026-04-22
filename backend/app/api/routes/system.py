"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_ops_access
from ...api.schemas import RunCycleResult
from ...db.session import get_db
from ...services.audit_service import record_admin_audit_log
from ...services.pipeline_control import monitoring_pipeline_guard
from ...services.run_cycle_service import run_monitoring_cycle

router = APIRouter()


@router.post("/run-cycle", response_model=RunCycleResult)
async def run_cycle(
    request: Request,
    actor=Depends(require_ops_access),
    db: AsyncSession = Depends(get_db),
) -> RunCycleResult:
    """Run cycle for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        request: request value used by this routine (type `Request`).
        actor: actor value used by this routine (optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `RunCycleResult` result produced by the routine.
    """
    async with monitoring_pipeline_guard(wait=False) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Monitoring pipeline is already running",
            )
        result = RunCycleResult(**await run_monitoring_cycle(db))
        await record_admin_audit_log(
            db,
            actor=actor,
            action="system.run_cycle",
            target_type="system",
            target_id="run-cycle",
            ip_address=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
            details=result.model_dump(),
        )
        return result
