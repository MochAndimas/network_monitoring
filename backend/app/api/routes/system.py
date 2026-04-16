from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_admin_access
from ...api.schemas import RunCycleResult
from ...db.session import get_db
from ...services.pipeline_control import monitoring_pipeline_guard
from ...services.run_cycle_service import run_monitoring_cycle

router = APIRouter()


@router.post("/run-cycle", response_model=RunCycleResult, dependencies=[Depends(require_admin_access)])
async def run_cycle(db: AsyncSession = Depends(get_db)) -> RunCycleResult:
    async with monitoring_pipeline_guard(wait=False) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Monitoring pipeline is already running",
            )
        return RunCycleResult(**await run_monitoring_cycle(db))
