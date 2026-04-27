"""Define module logic for `backend/app/scheduler/worker.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from ..core.config import configure_logging, settings
from ..core.security import validate_auth_configuration
from ..db.init_db import init_db
from ..db.session import SessionLocal
from ..services.auth_service import ensure_bootstrap_admin
from .scheduler import create_scheduler


logger = logging.getLogger("network_monitoring.scheduler.worker")


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Perform install signal handlers.

    Args:
        stop_event: Parameter input untuk routine ini.

    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows event loops may not support custom signal handlers.
            continue


async def run_scheduler_worker() -> None:
    """Run scheduler worker for scheduler execution workflows.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    configure_logging()
    validate_auth_configuration()
    if settings.app_env.lower() != "production":
        await init_db()
    async with SessionLocal() as db:
        await ensure_bootstrap_admin(db)

    if not settings.scheduler_enabled:
        logger.warning("Scheduler worker started with scheduler disabled; exiting.")
        return

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler worker started")
    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler worker stopped")


def main() -> None:
    """Return main for scheduler execution workflows.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    asyncio.run(run_scheduler_worker())


if __name__ == "__main__":
    main()
