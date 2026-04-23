"""Provide database engine, session, and initialization helpers for the network monitoring project."""

from .base import Base
from .session import engine
from ..models import alert, device, incident, metric, metric_daily_rollup, threshold, user  # noqa: F401


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    import asyncio

    asyncio.run(init_db())
    print("Database tables created.")
