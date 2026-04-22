"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.schemas import IncidentItem
from ...db.session import get_db
from ...repositories.incident_repository import IncidentRepository

router = APIRouter()


@router.get("", response_model=list[IncidentItem])
async def list_incidents(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[IncidentItem]:
    """Return a list of incidents for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        status: status value used by this routine (type `str | None`, optional).
        limit: limit value used by this routine (type `int`, optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `list[IncidentItem]` result produced by the routine.
    """
    return [IncidentItem(**row) for row in await IncidentRepository(db).list_incident_rows(status=status, limit=limit)]
