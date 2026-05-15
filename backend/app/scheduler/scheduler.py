"""scheduler support code for scheduler."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..core.config import settings
from .jobs import register_jobs


def create_scheduler() -> AsyncIOScheduler:
    """Create scheduler for scheduled monitoring execution."""
    scheduler = AsyncIOScheduler(timezone=settings.scheduler.timezone)
    register_jobs(scheduler)
    return scheduler
