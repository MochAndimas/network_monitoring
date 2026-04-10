from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...api.deps import require_internal_api_key
from ...api.schemas import RunCycleResult
from ...db.session import get_db
from ...services.run_cycle_service import run_monitoring_cycle

router = APIRouter()


@router.post("/run-cycle", response_model=RunCycleResult, dependencies=[Depends(require_internal_api_key)])
async def run_cycle(db: Session = Depends(get_db)) -> RunCycleResult:
    return RunCycleResult(**run_monitoring_cycle(db))
