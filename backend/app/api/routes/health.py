from fastapi import APIRouter

from ...db.session import check_database_connection

router = APIRouter()


@router.get("")
async def health() -> dict:
    database_ok = check_database_connection()
    return {
        "status": "ok" if database_ok else "degraded",
        "database": "up" if database_ok else "down",
    }
