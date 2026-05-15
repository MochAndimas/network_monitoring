"""Explicit local-only schema bootstrap helper.

Production and shared environments should use Alembic migrations. This helper is
only called when DATABASE_AUTO_CREATE_TABLES=true or when run manually.
"""

from .base import Base
from .session import engine
from ..models import alert, device, incident, metric, metric_daily_rollup, retention_bucket_progress, threshold, user  # noqa: F401


async def init_db() -> None:
    """Return init db for database initialization and sessions."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    import asyncio

    asyncio.run(init_db())
    print("Database tables created.")
