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
    return [IncidentItem(**row) for row in await IncidentRepository(db).list_incident_rows(status=status, limit=limit)]
