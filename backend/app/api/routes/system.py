"""FastAPI routes for system endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_ops_access
from ...api.schemas import RunCycleResult
from ...db.session import get_db
from ...services.audit_service import record_admin_audit_log
from ...services.pipeline_control import MONITORING_FULL_CYCLE_LOCK_SCOPES, monitoring_pipeline_multi_guard
from ...services.run_cycle_service import run_monitoring_cycle

router = APIRouter()


@router.post("/run-cycle", response_model=RunCycleResult)
async def run_cycle(
    request: Request,
    actor=Depends(require_ops_access),
    db: AsyncSession = Depends(get_db),
) -> RunCycleResult:
    """Handle the cycle endpoint."""
    async with monitoring_pipeline_multi_guard(wait=False, scopes=MONITORING_FULL_CYCLE_LOCK_SCOPES) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Monitoring pipeline is already running",
            )
        if db.in_transaction():
            await db.commit()
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
