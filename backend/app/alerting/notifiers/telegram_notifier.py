"""notifiers support code for telegram notifier."""

from __future__ import annotations

import logging

from ...core.config import settings

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None  # type: ignore[assignment, misc]


logger = logging.getLogger("network_monitoring.telegram")


async def send_telegram_alert(message: str) -> bool:
    """Send a Telegram alert and report whether Telegram accepted it."""
    telegram_settings = settings.telegram
    if not telegram_settings.bot_token or not telegram_settings.chat_id or Bot is None:
        logger.info("Telegram notifier is not configured; alert skipped: %s", message)
        return False

    try:
        bot = Bot(token=telegram_settings.bot_token)
        await bot.send_message(chat_id=telegram_settings.chat_id, text=message)
    except Exception:
        logger.exception("Telegram alert could not be sent")
        return False

    logger.info("Telegram alert sent")
    return True
