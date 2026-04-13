from fastapi import APIRouter, Response, status

from ...db.session import check_database_connection

router = APIRouter()


@router.get("")
async def health(response: Response) -> dict:
    database_ok = await check_database_connection()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if database_ok else "degraded",
        "database": "up" if database_ok else "down",
    }
