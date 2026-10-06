"""Run, inspect, or redrive the durable Telegram worker without API involvement."""

import argparse
import asyncio
from datetime import timedelta
import logging
import socket

from sqlalchemy import select
from telegram import Bot
from ..core.config import configure_logging, settings
from ..core.time import utcnow
from ..db.session import SessionLocal, engine
from ..models.notification_worker import NotificationWorker
from ..services.notification_maintenance import redrive_notification
from ..services.notification_runtime import run_notification_runtime
from ..services.notification_worker_process import run_notification_process
from ..services.telegram_outbox_writer import TelegramOutboxWriter


async def run(command: str, job_id: int | None = None) -> None:
    identity = socket.gethostname()[:64]
    try:
        if command == "health":
            async with SessionLocal() as db:
                alive = await db.scalar(
                    select(NotificationWorker.worker_id).where(
                        NotificationWorker.worker_id == identity,
                        NotificationWorker.status == "running",
                        NotificationWorker.updated_at >= utcnow() - timedelta(seconds=45),
                    )
                )
            if not alive:
                raise SystemExit(1)
            return
        if command == "redrive":
            if job_id is None:
                raise ValueError("redrive requires --job-id")
            async with SessionLocal.begin() as db:
                changed = await redrive_notification(db, job_id, now=utcnow())
            print("Job queued for retry" if changed else "Job is not dead; unchanged")
            return
        telegram = settings.telegram
        if not telegram.bot_token or not telegram.chat_id:
            raise ValueError("Notification worker requires Telegram token and numeric chat ID")
        TelegramOutboxWriter(telegram.chat_id)
        # SDK/HTTP request logs can embed the bot token in URLs.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        async with Bot(token=telegram.bot_token) as bot:

            async def send(destination: str, message: str) -> bool:
                await bot.send_message(chat_id=destination, text=message)
                return True

            async def worker(stop: asyncio.Event):
                return await run_notification_runtime(SessionLocal, send, stop, worker_id=identity)

            await run_notification_process(worker)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "health", "redrive"), nargs="?", default="run")
    parser.add_argument("--job-id", type=int)
    args = parser.parse_args()
    configure_logging()
    try:
        asyncio.run(run(args.command, args.job_id))
    except Exception:
        # Fail closed without a provider/DB traceback containing credentials.
        logging.getLogger(__name__).error(
            "Notification process failed; check configuration, schema and database availability"
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
