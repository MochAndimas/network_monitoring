"""Define module logic for `backend/app/scheduler/scheduler.py`.

This module contains project-specific implementation details.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .jobs import register_jobs


def create_scheduler() -> AsyncIOScheduler:
    """Create scheduler for scheduler execution workflows.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")
    register_jobs(scheduler)
    return scheduler
