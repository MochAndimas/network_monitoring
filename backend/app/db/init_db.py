"""Define module logic for `backend/app/db/init_db.py`.

This module contains project-specific implementation details.
"""

from .base import Base
from .session import engine
from ..models import alert, device, incident, metric, metric_daily_rollup, threshold, user  # noqa: F401


async def init_db() -> None:
    """Initialize database schema metadata in the current engine.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    import asyncio

    asyncio.run(init_db())
    print("Database tables created.")
