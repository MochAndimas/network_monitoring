"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import AlertItem
from ...db.session import get_db
from ...repositories.alert_repository import AlertRepository

router = APIRouter()


@router.get("/active", response_model=list[AlertItem])
async def get_active_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertItem]:
    return [AlertItem(**row) for row in await AlertRepository(db).list_active_alert_rows()]
