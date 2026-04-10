from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...api.schemas import DashboardSummary
from ...db.session import get_db
from ...services.monitoring_service import build_dashboard_summary

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: Session = Depends(get_db)) -> DashboardSummary:
    return DashboardSummary(**build_dashboard_summary(db))
