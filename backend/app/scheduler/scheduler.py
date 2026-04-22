"""Provide background scheduler and worker jobs for the network monitoring project."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .jobs import register_jobs


def create_scheduler() -> AsyncIOScheduler:
    """Create scheduler for background scheduler and worker jobs.

    Returns:
        `AsyncIOScheduler` result produced by the routine.
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")
    register_jobs(scheduler)
    return scheduler
