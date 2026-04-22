"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import AlertItem
from ...db.session import get_db
from ...repositories.alert_repository import AlertRepository

router = APIRouter()


@router.get("/active", response_model=list[AlertItem])
async def get_active_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertItem]:
    """Return active alerts for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `list[AlertItem]` result produced by the routine.
    """
    return [AlertItem(**row) for row in await AlertRepository(db).list_active_alert_rows()]
