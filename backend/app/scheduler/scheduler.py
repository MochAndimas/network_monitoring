from apscheduler.schedulers.background import BackgroundScheduler

from .jobs import register_jobs


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    register_jobs(scheduler)
    return scheduler
