"""FastAPI routes for dashboard endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import DashboardSummary
from ...db.session import get_db
from ...services.dashboard_overview_service import get_overview_payload, get_problem_device_rows
from ...services.monitoring_service import build_dashboard_summary

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    """Return get summary used by dashboard payloads."""
    return DashboardSummary(**await build_dashboard_summary(db))


@router.get("/overview-panels")
async def get_overview_panels(
    snapshot_limit: int = Query(default=12, ge=1, le=100),
    alerts_limit: int = Query(default=5, ge=1, le=50),
    incidents_limit: int = Query(default=5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return get overview panels used by dashboard payloads."""
    return await get_overview_payload(
        db,
        snapshot_limit=snapshot_limit,
        alerts_limit=alerts_limit,
        incidents_limit=incidents_limit,
        include_problem_devices=False,
    )


@router.get("/problem-devices")
async def get_problem_devices(
    limit: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return get problem devices used by dashboard payloads."""
    return await get_problem_device_rows(db, limit=limit)


@router.get("/overview-data")
async def get_overview_data(db: AsyncSession = Depends(get_db)) -> dict:
    """Return get overview data used by dashboard payloads."""
    return await get_overview_payload(
        db,
        snapshot_limit=12,
        alerts_limit=5,
        incidents_limit=5,
        include_problem_devices=True,
    )
