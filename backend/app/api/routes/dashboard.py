from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import DashboardSummary
from ...db.session import get_db
from ...services.monitoring_service import build_dashboard_summary

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    return DashboardSummary(**await build_dashboard_summary(db))
