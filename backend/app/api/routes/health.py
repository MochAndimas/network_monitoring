"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Response, status

from ...db.session import check_database_connection
from ...services.observability_service import build_scheduler_operational_alerts, list_scheduler_job_statuses
from ...db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

router = APIRouter()


@router.get("")
async def health(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Report health for the requested operation for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        response: response value used by this routine (type `Response`).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `dict` result produced by the routine.
    """
    database_ok = await check_database_connection()
    scheduler_alerts = build_scheduler_operational_alerts(await list_scheduler_job_statuses(db))
    if not database_ok or scheduler_alerts:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if database_ok and not scheduler_alerts else "degraded",
        "database": "up" if database_ok else "down",
        "scheduler": "up" if not scheduler_alerts else "degraded",
    }


@router.get("/live")
async def health_live() -> dict:
    """Report health for live for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Returns:
        `dict` result produced by the routine.
    """
    return {"status": "ok"}


@router.get("/dependencies")
async def health_dependencies(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Report health for dependencies for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        response: response value used by this routine (type `Response`).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `dict` result produced by the routine.
    """
    database_ok = await check_database_connection()
    scheduler_statuses = await list_scheduler_job_statuses(db)
    scheduler_alerts = build_scheduler_operational_alerts(scheduler_statuses)
    if not database_ok or scheduler_alerts:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "database": "up" if database_ok else "down",
        "scheduler_jobs": [
            {
                "job_name": job.job_name,
                "is_running": job.is_running,
                "consecutive_failures": job.consecutive_failures,
                "last_succeeded_at": job.last_succeeded_at,
                "last_failed_at": job.last_failed_at,
            }
            for job in scheduler_statuses
        ],
        "scheduler_alerts": scheduler_alerts,
    }


@router.get("/ready")
async def health_ready(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Report health for ready for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        response: response value used by this routine (type `Response`).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `dict` result produced by the routine.
    """
    database_ok = await check_database_connection()
    scheduler_statuses = await list_scheduler_job_statuses(db)
    scheduler_alerts = build_scheduler_operational_alerts(scheduler_statuses)
    ready = database_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "dependencies": {
            "database": "up" if database_ok else "down",
            "scheduler_jobs": [
                {
                    "job_name": job.job_name,
                    "is_running": job.is_running,
                    "consecutive_failures": job.consecutive_failures,
                    "last_succeeded_at": job.last_succeeded_at,
                    "last_failed_at": job.last_failed_at,
                }
                for job in scheduler_statuses
            ],
            "scheduler_alerts": scheduler_alerts,
            "scheduler": "degraded" if scheduler_alerts else "up",
        },
    }
