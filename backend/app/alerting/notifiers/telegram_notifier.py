from __future__ import annotations

import asyncio
import logging
from threading import Thread

from ...core.config import settings

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None


logger = logging.getLogger("network_monitoring.telegram")


def send_telegram_alert(message: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id or Bot is None:
        logger.info("Telegram notifier is not configured; alert skipped: %s", message)
        return

    async def _send() -> None:
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=settings.telegram_chat_id, text=message)

    try:
        _run_async(_send)
    except Exception:
        logger.exception("Telegram alert could not be sent")
        return

    logger.info("Telegram alert sent")


def _run_async(coro_factory) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro_factory())
        return

    errors: list[BaseException] = []

    def runner() -> None:
        try:
            asyncio.run(coro_factory())
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
