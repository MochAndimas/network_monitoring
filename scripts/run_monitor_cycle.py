"""Provide operator and maintenance scripts for the network monitoring project."""

import asyncio

from backend.app.db.init_db import init_db
from backend.app.db.session import SessionLocal
from backend.app.services.run_cycle_service import run_monitoring_cycle


async def main() -> None:
    """Handle main for operator and maintenance scripts. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Returns:
        None. The routine is executed for its side effects.
    """
    await init_db()
    async with SessionLocal() as db:
        result = await run_monitoring_cycle(db)
    print("Monitoring cycle completed.")
    for key, value in result.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
