"""Provide operator and maintenance scripts for the network monitoring project."""

import asyncio

from backend.app.db.init_db import init_db
from backend.app.db.session import SessionLocal
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.services.run_cycle_service import run_monitoring_cycle
from backend.app.services.threshold_service import ensure_default_thresholds
from scripts.seed_devices import SEED_DEVICES


async def main() -> None:
    """Handle main for operator and maintenance scripts. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Returns:
        None. The routine is executed for its side effects.
    """
    await init_db()
    async with SessionLocal() as db:
        devices = await DeviceRepository(db).upsert_devices(SEED_DEVICES)
        await ensure_default_thresholds(db)
        result = await run_monitoring_cycle(db)

    print(f"Bootstrapped {len(devices)} devices and executed one monitoring cycle.")
    for key, value in result.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
