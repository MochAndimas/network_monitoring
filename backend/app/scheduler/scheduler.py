from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .jobs import register_jobs


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")
    register_jobs(scheduler)
    return scheduler
